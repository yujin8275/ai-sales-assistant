"""로컬 PDF/Excel 원본 읽기. DB를 수정하지 않습니다."""
from pathlib import Path
import hashlib
import re
import pdfplumber
import fitz
from openpyxl import load_workbook
from database.images import build_image_entry

BASE = Path(__file__).resolve().parent
RAW = BASE / 'data' / 'inbox'
CATALOG_DIR = RAW / 'catalogs'
MANUAL_DIR = RAW / 'manuals'
SALES_DIR = RAW / 'sales'

# 제조사별 카탈로그 레이아웃 차이는 파서에서 처리합니다.
SUPPORTED_VENDORS = {'Apple', 'Samsung', 'Xiaomi'}


def _files(folder, extension):
    """해당 폴더에 있는 파일만 가져옵니다. 빈 폴더는 허용합니다."""
    folder.mkdir(parents=True, exist_ok=True)
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() == extension
                  and not p.name.startswith(('~$', '.')))


def discover_files():
    """파일 이름과 무관하게 inbox 탐색. 한 배치의 판매 Excel은 1개 이하."""
    catalogs = _files(CATALOG_DIR, '.pdf')
    manuals = _files(MANUAL_DIR, '.pdf')
    sales = _files(SALES_DIR, '.xlsx')
    if len(sales) > 1:
        raise ValueError('sales 폴더에 Excel이 여러 개 있습니다. 한 번에 1개만 처리하세요: '
                         + ', '.join(p.name for p in sales))
    return {'catalogs': catalogs, 'manuals': manuals, 'sales': sales}


def file_manifest(inputs):
    """미리보기-승인 사이 파일 내용이 바뀌지 않았는지 확인할 SHA-256."""
    result = []
    for kind, paths in inputs.items():
        for path in paths:
            data_hash = hashlib.sha256()
            with path.open('rb') as fh:
                for block in iter(lambda: fh.read(1024 * 1024), b''):
                    data_hash.update(block)
            result.append({'kind': kind, 'name': path.name,
                           'sha256': data_hash.hexdigest(), 'bytes': path.stat().st_size})
    return result


def manifest_matches(manifest):
    """신규/삭제/수정 모두 감지. 디렉터리 내부 실제 파일만 확인."""
    inputs = discover_files()
    return file_manifest(inputs) == manifest


def _section(text, begin, end=None):
    m = re.search(rf'(?im)^\s*{re.escape(begin)}\b.*$', text)
    if not m:
        raise ValueError(f'PDF 섹션을 찾지 못했습니다: {begin}')
    remainder = text[m.end():]
    if end:
        z = re.search(rf'(?im)^\s*{re.escape(end)}\b.*$', remainder)
        if not z:
            raise ValueError(f'PDF 섹션을 찾지 못했습니다: {end}')
        remainder = remainder[:z.start()]
    return remainder.strip()


def _field(text, key, required=True):
    m = re.search(rf'(?m)^\s*{re.escape(key)}\s+(.+?)\s*$', text)
    if not m:
        if required:
            raise ValueError(f'필드를 찾지 못했습니다: {key}')
        return None
    return m.group(1).strip()


def _num(value):
    return float(str(value).replace(',', ''))


def _camera_zoom(value):
    """삼성: 광학 줌 우선, 수치 없는/미공개는 NULL. Apple/Xiaomi: 원본 수치."""
    if not value or value.strip() in ('-', '미공개'):
        return None
    value = value.strip()
    if re.fullmatch(r'\d+(?:\.\d+)?', value):
        return float(value)
    # '3배 광학 / 최대 30배 디지털' -> 3.0
    # '5배 광학 / 광학 줌 수준 10배' -> 5.0
    for pattern in [r'(\d+(?:\.\d+)?)\s*배\s*광학', r'광학\s*줌\s*수준\s*(\d+(?:\.\d+)?)\s*배', r'(\d+(?:\.\d+)?)\s*배\s*디지털']:
        match = re.search(pattern, value)
        if match:
            return float(match.group(1))
    raise ValueError(f'해석할 수 없는 카메라 줌 표기: {value}')


def _parse_catalog_page(text, vendor, filename, page_number):
    product_id = _field(text, 'product_id')
    product = {
        'product_id': product_id,
        'category_id': 'CAT001',
        'product_name': _field(text, 'product_name'),
        'brand': _field(text, 'brand'),
        'product_tier': _field(text, 'product_tier').upper(),
        'release_date': _field(text, 'release_date'),
        'product_image_path': None,
    }
    if product['brand'] != vendor:
        raise ValueError(f'브랜드 오류 {filename} {page_number}p: {product["brand"]} != {vendor}')

    variants_section = _section(text, '02 product_variants', '03 product_specs')
    variants = []
    for line in variants_section.splitlines():
        # SKU | 색상(공백 가능) | RAM | 저장공간. SKU는 카탈로그 원문 그대로 사용.
        match = re.match(r'^([A-Z0-9-]+)\s+(.+?)\s+(\d+)\s+(\d+)\s*$', line.strip())
        if match:
            sku, color, ram, storage = match.groups()
            variants.append({'sku': sku, 'product_id': product_id, 'color': color,
                             'ram_capacity': int(ram), 'storage_capacity': int(storage)})
    if not variants:
        raise ValueError(f'SKU를 추출하지 못했습니다: {filename} {page_number}p')

    spec_section = _section(text, '03 product_specs', '04 display_specs')
    if vendor == 'Samsung':
        def pick(pattern):
            m = re.search(pattern, spec_section, re.I)
            if not m:
                raise ValueError(f'삼성 제품 사양 패턴 불일치: {product_id}: {pattern}')
            return m.group(1).strip()
        spec = {
            'product_id': product_id,
            'processor': pick(r'processor\s+(.+?)\s+thickness\s*\(mm\)'),
            'thickness': _num(pick(r'thickness\s*\(mm\)\s+([\d.]+)')),
            'width': _num(pick(r'width\s*\(mm\)\s+([\d.]+)')),
            'height': _num(pick(r'height\s*\(mm\)\s+([\d.]+)')),
            'weight': int(_num(pick(r'weight\s*\(g\)\s+([\d,]+)'))),
            'battery_capacity': int(_num(pick(r'battery_capacity\s*\(mAh\)\s+([\d,]+)'))),
        }
    else:
        rows = [x.strip() for x in spec_section.splitlines() if x.strip()]
        found = None
        for line in rows:
            m = re.match(r'^(.+?)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+(\d+)\s+(\d+)$', line)
            if m:
                found = m
                break
        if not found:
            raise ValueError(f'제품 사양을 추출하지 못했습니다: {product_id}')
        processor, thickness, width, height, weight, battery = found.groups()
        spec = {'product_id': product_id, 'processor': processor, 'thickness': float(thickness),
                'width': float(width), 'height': float(height), 'weight': int(weight),
                'battery_capacity': int(battery)}

    display_section = _section(text, '04 display_specs', '05 cameras')
    if vendor == 'Samsung':
        # 제품별 본문 한 줄: PRODUCT_ID | 패널(공백 포함) | 174.9 mm | 최대 2,600 nits 또는 공식 자료 미기재
        m = re.search(rf'(?m)^\s*{re.escape(product_id)}\s+(.+?)\s+([\d.]+)\s*mm\s+(.+?)\s*$', display_section)
        if not m:
            raise ValueError(f'디스플레이 추출 실패: {product_id}')
        panel, size_mm, brightness = m.groups()
        size_in = round(float(size_mm) / 25.4, 2)
        nit_match = re.search(r'([\d,]+)\s*nits?', brightness)
        brightness_value = int(nit_match.group(1).replace(',', '')) if nit_match else None
    else:
        rows = [x.strip() for x in display_section.splitlines() if x.strip()]
        m = next((re.match(r'^(.+?)\s+([\d.]+)\s+(\d+)\s*$', row) for row in rows
                  if re.match(r'^(.+?)\s+([\d.]+)\s+(\d+)\s*$', row)), None)
        if not m:
            raise ValueError(f'디스플레이 추출 실패: {product_id}')
        panel, size_in, brightness_value = m.groups()
        size_in = float(size_in)
        brightness_value = int(brightness_value)
    display = {'product_id': product_id, 'display_panel': panel, 'display_size': size_in,
               'display_brightness': brightness_value}

    camera_section = _section(text, '05 cameras')
    cameras = []
    for line in camera_section.splitlines():
        line = line.strip()
        if not line or line.startswith(('camera_id', '※')):
            continue
        m = re.match(r'^([A-Z0-9-]+)\s+(.+?)\s+([\d.]+)\s+([fF]/?[\d.\-]+)\s+(.+?)\s+(TRUE|FALSE|미공개)\s*$', line)
        if m:
            camera_id, camera_type, resolution, aperture, zoom, ois = m.groups()
            cameras.append({'camera_id': camera_id, 'product_id': product_id,
                            'camera_type': camera_type, 'resolution_mp': float(resolution),
                            'aperture': aperture, 'max_zoom': _camera_zoom(zoom),
                            'ois': None if ois == '미공개' else ois == 'TRUE'})
    if not cameras:
        raise ValueError(f'카메라 사양 추출 실패: {product_id}')
    return product, variants, spec, display, cameras


def read_catalogs(paths=None):
    """파일명과 무관하게 PDF 내용의 brand 필드로 제조사 파서를 선택합니다."""
    paths = paths if paths is not None else _files(CATALOG_DIR, '.pdf')
    data = {'products': [], 'product_variants': [], 'product_specs': [], 'display_specs': [], 'cameras': [], 'images': []}
    for path in paths:
        with pdfplumber.open(path) as pdf, fitz.open(str(path)) as image_pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ''
                vendor = _field(text, 'brand')
                if vendor not in SUPPORTED_VENDORS:
                    raise ValueError(f'지원하지 않는 제조사/카탈로그 구조: {path.name} {page_num}p (brand={vendor})')
                product, variants, spec, display, cameras = _parse_catalog_page(
                    text, vendor, path.name, page_num
                )
                image_entry = build_image_entry(path, page_num - 1, product['product_id'], image_pdf)
                if image_entry:
                    product['product_image_path'] = image_entry['relative_path']
                    data['images'].append(image_entry)
                data['products'].append(product)
                data['product_variants'].extend(variants)
                data['product_specs'].append(spec)
                data['display_specs'].append(display)
                data['cameras'].extend(cameras)
    return data


def read_manuals(paths=None):
    """상품 ID는 설명서 본문의 상품 ID/상품코드에서 추출합니다."""
    paths = paths if paths is not None else _files(MANUAL_DIR, '.pdf')
    chunks = []
    for path in paths:
        document_id = 'DOC-' + hashlib.sha256(path.read_bytes()).hexdigest()[:16].upper()
        with pdfplumber.open(path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                text = (page.extract_text() or '').strip()
                header = '\n'.join(text.splitlines()[:14])
                header_lines = [ln.strip() for ln in header.splitlines() if ln.strip()]
                pid = None
                for j, line in enumerate(header_lines):
                    if not re.search(r'상품\s*(?:ID|코드)', line, re.I):
                        continue
                    # Apple 문서는 ID가 '상품 ID' 라벨의 바로 윗줄에 위치함.
                    # Samsung/Xiaomi 문서는 한 줄에 '상품코드 SAM001' 형태가 주로 사용됨.
                    trailing = re.sub(r'^.*?상품\s*(?:ID|코드)\s*[:：]?', '', line, flags=re.I).strip()
                    candidates = [trailing]
                    if j > 0:
                        candidates.append(header_lines[j - 1])
                    if j + 1 < len(header_lines):
                        candidates.append(header_lines[j + 1])
                    for candidate in candidates:
                        code = re.match(r'^([A-Z][A-Z0-9-]*\d[A-Z0-9-]*)$', candidate)
                        if code:
                            pid = code.group(1)
                            break
                    if pid:
                        break
                if not pid:
                    raise ValueError(f'설명서 제품 ID를 찾지 못했습니다: {path.name} {page_num}p')
                lines = [x.strip() for x in text.splitlines() if x.strip()]
                lines = [x for x in lines if not re.fullmatch(r'\d+\s*/\s*\d+', x)]
                chunks.append({
                    'chunk_id': f'CH-{pid}-001',
                    'document_id': document_id,
                    'product_id': pid,
                    'metadata': {'source_file': path.name, 'page_number': page_num, 'chunk_index': 1},
                    'content': '\n'.join(lines),
                    'embedding': [],
                })
    return chunks


def _excel_rows(wb, sheet_name):
    if sheet_name not in wb.sheetnames:
        raise ValueError(f'엑셀 시트가 없습니다: {sheet_name}')
    rows = wb[sheet_name].iter_rows(values_only=True)
    header = [str(c).strip() if c is not None else '' for c in next(rows)]
    result = []
    for row in rows:
        if not any(v is not None for v in row):
            continue
        obj = {}
        for key, value in zip(header, row):
            if key:
                obj[key] = value.isoformat() if hasattr(value, 'isoformat') else value
        result.append(obj)
    return result


EXCEL_SHEETS = {
    'products_ref': ('상품참조', {'product_id', 'product_name', 'brand', 'category_id'}),
    'variants_ref': ('SKU목록', {'sku', 'product_id', 'color', 'ram_capacity', 'storage_capacity'}),
    'inventory_prices': ('가격재고', {'sku', 'list_price', 'sale_price', 'stock_quantity'}),
    'sku_sales': ('SKU판매량', {'sku', 'sales_quantity_3m', 'sales_reference_date'}),
    'card_promotions': ('카드할인정책', {'promotion_id', 'card_company', 'discount_rate', 'start_date', 'end_date', 'applies_to_all', 'is_active'}),
    'promotion_products': ('할인대상기종', {'promotion_id', 'product_id'}),
}


def read_sales_excel(path):
    """시트 누락은 허용: 가격 업데이트만 있는 Excel도 처리 가능."""
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        result = {}
        available = set()
        for key, (sheet, mandatory) in EXCEL_SHEETS.items():
            if sheet not in wb.sheetnames:
                result[key] = []
                continue
            available.add(key)
            header = set(str(v).strip() for v in next(wb[sheet].values) if v is not None)
            missing = mandatory - header
            if missing:
                raise ValueError(f'{path.name} / {sheet}: 필수 열 누락: {sorted(missing)}')
            result[key] = _excel_rows(wb, sheet)
        if not any(k in available for k in ('inventory_prices', 'sku_sales', 'card_promotions', 'promotion_products')):
            raise ValueError('Excel에 처리 가능한 운영 시트가 없습니다.')
        result['_present_sheets'] = sorted(available)
        return result
    finally:
        wb.close()


def extract_all(inputs=None):
    """inbox의 존재하는 파일만 처리. 기존 DB 상태 검증은 transform 모듈 담당."""
    inputs = inputs if inputs is not None else discover_files()
    if not any(inputs.values()):
        raise ValueError('inbox가 비어 있습니다. catalogs/manuals/sales 폴더에 파일을 넣으세요.')
    catalogs = read_catalogs(inputs['catalogs']) if inputs['catalogs'] else {
        'products': [], 'product_variants': [], 'product_specs': [],
        'display_specs': [], 'cameras': []}
    manuals = read_manuals(inputs['manuals']) if inputs['manuals'] else []
    sales = read_sales_excel(inputs['sales'][0]) if inputs['sales'] else {
        **{key: [] for key in EXCEL_SHEETS}, '_present_sheets': []}
    return {'catalogs': catalogs, 'manuals': manuals, 'sales': sales,
            'source_files': file_manifest(inputs)}
