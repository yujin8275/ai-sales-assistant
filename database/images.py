"""Reusable PDF product-image extraction and local PNG storage.

This module NEVER changes PostgreSQL. The normal ingestion pipeline imports
build_image_entry()/materialize_preview_images() and persists relative paths
through its existing, explicitly approved database save routine.

For already imported catalogs, the optional *generic* CLI exports PNG files and
produces a standalone SQL file. An operator must review and execute that SQL
separately; there is no DB-specific backfill or automatic UPDATE command here.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import tempfile
from pathlib import Path

import fitz  # PyMuPDF
import pdfplumber

DATA_DIR = Path(__file__).resolve().parent / 'data'
IMAGES_DIR = DATA_DIR / 'product_images'
INBOX_CATALOG_DIR = DATA_DIR / 'inbox' / 'catalogs'
PROCESSED_DIR = DATA_DIR / 'processed'

PRODUCT_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,40}$')
PRODUCT_ROW_PATTERN = re.compile(r'(?m)^\s*product_id\s+([A-Za-z0-9_-]+)\s*$')


def _safe_id(product_id: str) -> str:
    product_id = str(product_id)
    if not PRODUCT_ID_PATTERN.fullmatch(product_id):
        raise ValueError(f'Invalid product_id for image path: {product_id!r}')
    return product_id


def _image_bytes(page: fitz.Page) -> bytes | None:
    """Render the largest *displayed* photo rectangle in a supported catalog.

    Avoids extracting hidden/unplaced PDF image resources. Layout-dependent:
    validate a sample when a vendor changes its catalog design.
    """
    candidates = []
    for entry in page.get_image_info(xrefs=True):
        bbox = fitz.Rect(entry['bbox'])
        if (entry['width'] >= 160 and entry['height'] >= 150
                and bbox.width >= 60 and bbox.height >= 60):
            candidates.append((bbox.width * bbox.height, bbox))
    if not candidates:
        return None
    _, region = max(candidates, key=lambda item: item[0])
    pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), clip=region,
                          colorspace=fitz.csRGB, alpha=False)
    return pix.tobytes('png')


def build_image_entry(pdf_path: Path, page_index: int, product_id: str, doc=None):
    """Compute image metadata without creating a file or changing the DB."""
    pdf_path = Path(pdf_path)
    product_id = _safe_id(product_id)
    if doc is None:
        with fitz.open(str(pdf_path)) as pdf:
            return build_image_entry(pdf_path, page_index, product_id, pdf)
    data = _image_bytes(doc[page_index])
    if data is None:
        return None
    sha256 = hashlib.sha256(data).hexdigest()
    return {
        'product_id': product_id,
        'source_file': pdf_path.name,
        'page_number': page_index + 1,
        'sha256': sha256,
        'relative_path': f'product_images/{product_id}_{sha256[:12]}.png',
    }


def _safe_target(entry: dict) -> Path:
    product_id = _safe_id(entry['product_id'])
    sha256 = entry['sha256']
    if not re.fullmatch(r'[0-9a-f]{64}', str(sha256)):
        raise ValueError('Invalid image SHA-256')
    expected = f'product_images/{product_id}_{sha256[:12]}.png'
    if entry['relative_path'] != expected:
        raise ValueError('Image path does not match product ID and SHA-256')
    return IMAGES_DIR / Path(expected).name


def write_image_entry(entry: dict, pdf_path: Path) -> Path:
    """Atomically materialize a verified content-addressed PNG file.

    Old image files stay untouched. If a later DB transaction fails, an
    unreferenced PNG may remain but no DB image reference is corrupted.
    """
    pdf_path = Path(pdf_path)
    with fitz.open(str(pdf_path)) as doc:
        page_index = int(entry['page_number']) - 1
        if page_index < 0 or page_index >= len(doc):
            raise ValueError(f'Invalid page number: {entry["page_number"]}')
        checked = build_image_entry(pdf_path, page_index, entry['product_id'], doc)
        if checked is None or checked['sha256'] != entry['sha256']:
            raise ValueError(f'PDF image changed since preview: {pdf_path.name}')
        data = _image_bytes(doc[page_index])
    target = _safe_target(entry)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != entry['sha256']:
            raise RuntimeError(f'Image file collision: {target}')
        return target
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=target.stem + '_',
                                         suffix='.tmp', delete=False) as fh:
            temp_path = Path(fh.name)
            fh.write(data)
        os.replace(temp_path, target)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return target


def materialize_preview_images(entries, catalogs_folder=INBOX_CATALOG_DIR):
    """Reusable ingestion helper: write approved catalog images before DB save."""
    for entry in entries:
        src = Path(catalogs_folder) / entry['source_file']
        if not src.is_file():
            raise FileNotFoundError(f'Catalog no longer exists: {src}')
        write_image_entry(entry, src)


def export_catalog_images(catalog_dir: Path, sql_output: Path) -> dict:
    """Export image files from ANY catalog directory and generate reviewable SQL.

    Does not access PostgreSQL. Useful for catalog reprocessing, repairing
    missing image files, or exporting pictures independently of normal ETL.
    SQL changes only NULL image paths and must be executed explicitly by user.
    """
    catalog_dir = Path(catalog_dir)
    sql_output = Path(sql_output)
    if not catalog_dir.is_dir():
        raise FileNotFoundError(f'Catalog directory does not exist: {catalog_dir}')
    pdf_files = sorted(p for p in catalog_dir.iterdir()
                       if p.is_file() and p.suffix.lower() == '.pdf')
    if not pdf_files:
        raise ValueError(f'No PDF catalogs in: {catalog_dir}')

    entries = {}
    missing = []
    # First inspect ALL files. Avoid partial exports if product IDs are ambiguous.
    for pdf_path in pdf_files:
        with pdfplumber.open(pdf_path) as text_pdf, fitz.open(str(pdf_path)) as image_pdf:
            if len(text_pdf.pages) != len(image_pdf):
                raise ValueError(f'PDF page count mismatch: {pdf_path.name}')
            for page_index, page in enumerate(text_pdf.pages):
                text = page.extract_text() or ''
                match = PRODUCT_ROW_PATTERN.search(text)
                if not match:
                    raise ValueError(f'No product_id on {pdf_path.name} page {page_index + 1}')
                product_id = _safe_id(match.group(1))
                image_entry = build_image_entry(pdf_path, page_index, product_id, image_pdf)
                if image_entry is None:
                    missing.append(f'{pdf_path.name} page {page_index + 1}: {product_id}')
                    continue
                if product_id in entries:
                    previous = entries[product_id]
                    if previous['sha256'] != image_entry['sha256']:
                        raise ValueError(f'Ambiguous duplicate product image: {product_id}')
                    continue
                entries[product_id] = {**image_entry, '_pdf_path': pdf_path}

    if not entries:
        raise ValueError('No product photos found in the catalog PDFs')
    for entry in entries.values():
        write_image_entry(entry, entry['_pdf_path'])

    def quote(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    rows = ',\n'.join(
        f'    ({quote(pid)}, {quote(entry["relative_path"])})'
        for pid, entry in sorted(entries.items())
    )
    statement = f'''-- Generated from catalog PDFs. Review before running.
-- This script NEVER deletes records or overwrites non-NULL image paths.
-- It only records relative paths to PNG files already exported locally.
BEGIN;
WITH image_paths(product_id, relative_path) AS (
  VALUES
{rows}
)
UPDATE public.products AS p
SET product_image_path = image_paths.relative_path
FROM image_paths
WHERE p.product_id = image_paths.product_id
  AND p.product_image_path IS NULL
RETURNING p.product_id, p.product_name, p.product_image_path;
COMMIT;
'''
    sql_output.parent.mkdir(parents=True, exist_ok=True)
    sql_output.write_text(statement, encoding='utf-8')
    return {'catalogs': len(pdf_files), 'images': len(entries),
            'no_image_pages': missing, 'sql_path': str(sql_output)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Export product PNGs from catalog PDFs and generate SQL (NO DB updates)')
    parser.add_argument('--catalog-dir', type=Path, required=True,
                        help='Directory containing PDF catalogs (any folder)')
    parser.add_argument('--sql-output', type=Path,
                        default=PROCESSED_DIR / 'product_image_paths.sql',
                        help='Write an SQL UPDATE script for operator review/execution')
    args = parser.parse_args()
    result = export_catalog_images(args.catalog_dir, args.sql_output)
    print(f'Catalog PDFs: {result["catalogs"]}')
    print(f'Product PNGs created/reused: {result["images"]}')
    print(f'PNG directory: {IMAGES_DIR}')
    print(f'SQL script generated: {result["sql_path"]}')
    if result['no_image_pages']:
        print('No photo on: ' + ', '.join(result['no_image_pages'][:8]))
    print('PostgreSQL unchanged. Review SQL and run it manually if needed.')


if __name__ == '__main__':
    main()
