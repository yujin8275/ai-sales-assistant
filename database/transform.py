"""PDF·Excel -> DB용 JSON. 기존 DB와 신규 입력을 비교하되, 저장은 하지 않습니다."""
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
import json

RDB_TABLES = (
    'categories', 'products', 'product_variants', 'product_specs', 'display_specs',
    'cameras', 'inventory_prices', 'sku_sales', 'card_promotions', 'promotion_products',
)
KEY_COLUMNS = {
    'categories': ('category_id',), 'products': ('product_id',),
    'product_variants': ('sku',), 'product_specs': ('product_id',),
    'display_specs': ('product_id',), 'cameras': ('camera_id',),
    'inventory_prices': ('sku',), 'sku_sales': ('sku',),
    'card_promotions': ('promotion_id',),
    'promotion_products': ('promotion_id', 'product_id'),
}


def key_for(table, row):
    return tuple(row.get(k) for k in KEY_COLUMNS[table])


def _canonical(value):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, (int, float)):
        return str(Decimal(str(value)).normalize())
    if isinstance(value, datetime):
        return value.isoformat(sep=' ')
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        # PostgreSQL timestamptz / Excel 날짜 표기 일치
        return value.strip().replace('T', ' ') if len(value) >= 10 else value
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_canonical(v) for v in value]
    return value


def rows_equal(table, incoming, previous):
    # updated_at은 값이 변경되면 DB 트리거가 관리하므로 비교 대상에서 제외
    keys = (k for k in incoming if not (table == 'inventory_prices' and k == 'updated_at'))
    return all(_canonical(incoming.get(k)) == _canonical(previous.get(k)) for k in keys)


def state_fingerprint(state):
    """미리보기 이후 DB가 변했는지 확인할 경량 지문. embedding 실수 배열은 조회하지 않음."""
    from hashlib import sha256
    clean = {
        'rdb': {table: sorted((_canonical(row) for row in state['rdb'][table].values()),
                              key=lambda r: json.dumps(r, sort_keys=True, ensure_ascii=False))
                for table in RDB_TABLES},
        'chunks': sorted((_canonical(c) for c in state['chunks'].values()),
                         key=lambda r: r['chunk_id']),
    }
    payload = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return sha256(payload.encode('utf-8')).hexdigest()


def blank_state():
    return {'rdb': {table: {} for table in RDB_TABLES}, 'chunks': {}}


def _duplicates(rows, keys):
    counts = Counter(tuple(row.get(k) for k in keys) for row in rows)
    return [k for k, v in counts.items() if v > 1]


def make_preview(extracted, state):
    """state: database.load_state() 결과 (읽기 전용). 모든 파일 유형은 독립 실행 가능."""
    catalogs = extracted['catalogs']
    sales = extracted['sales']
    existing = state['rdb']
    errors, warnings = [], []

    rdb = {t: [] for t in RDB_TABLES}
    if catalogs['products']:
        rdb['categories'] = [{'category_id': 'CAT001', 'category_name': '스마트폰'}]
    for table in ('products', 'product_variants', 'product_specs', 'display_specs', 'cameras'):
        rdb[table] = [dict(row) for row in catalogs[table]]
    # 카탈로그에서 이미지가 빠져 있어도 기존에 등록한 이미지 경로는 지우지 않습니다.
    for product in rdb['products']:
        old = existing['products'].get((product['product_id'],))
        if old and not product.get('product_image_path'):
            product['product_image_path'] = old.get('product_image_path')
    for table in ('inventory_prices', 'sku_sales', 'card_promotions', 'promotion_products'):
        rdb[table] = sales[table]

    for table, rows in rdb.items():
        duplicates = _duplicates(rows, KEY_COLUMNS[table])
        if duplicates:
            errors.append(f'{table}: 중복 키 {duplicates[:4]}')
    for ref_table in ('products_ref', 'variants_ref'):
        ref_keys = ('product_id',) if ref_table == 'products_ref' else ('sku',)
        dup = _duplicates(sales[ref_table], ref_keys)
        if dup:
            errors.append(f'Excel {ref_table} 시트에 중복 ID가 있습니다: {dup[:4]}')
    if _duplicates(extracted['manuals'], ('chunk_id',)):
        errors.append('설명서에 같은 상품 ID가 중복됩니다. 동일 제품 설명서를 두 번 넣었는지 확인하세요.')

    # 이번에 제출한 데이터 + 현재 DB의 합집합으로 참조 검증
    products_by_id = {r['product_id']: r for r in existing['products'].values()}
    products_by_id.update({r['product_id']: r for r in rdb['products']})
    variants_by_sku = {r['sku']: r for r in existing['product_variants'].values()}
    variants_by_sku.update({r['sku']: r for r in rdb['product_variants']})
    promotions = {r['promotion_id']: r for r in existing['card_promotions'].values()}
    promotions.update({r['promotion_id']: r for r in rdb['card_promotions']})

    for table in ('product_variants', 'product_specs', 'display_specs', 'cameras'):
        for row in rdb[table]:
            if row['product_id'] not in products_by_id:
                errors.append(f'{table}: 존재하지 않는 제품 {row["product_id"]}')
    for table in ('inventory_prices', 'sku_sales'):
        for row in rdb[table]:
            if row['sku'] not in variants_by_sku:
                errors.append(f'{table}: 미등록 SKU {row["sku"]}')
    for row in rdb['promotion_products']:
        if row['product_id'] not in products_by_id or row['promotion_id'] not in promotions:
            errors.append(f'할인 대상 제품 또는 정책 미등록: {row}')

    # Excel의 참조 시트가 있다면 카탈로그+DB에 존재하는 ID와 옵션 내용을 대조
    for row in sales['products_ref']:
        pid = row['product_id']
        src = products_by_id.get(pid)
        if not src:
            errors.append(f'Excel 상품참조: 미등록 제품 {pid}')
        elif any(_canonical(src.get(k)) != _canonical(row.get(k))
                 for k in ('product_name', 'brand', 'category_id')):
            errors.append(f'Excel 상품참조: 제품 정보 불일치 {pid}')
    for row in sales['variants_ref']:
        sku = row['sku']
        src = variants_by_sku.get(sku)
        if not src:
            errors.append(f'Excel SKU목록: 미등록 SKU {sku}')
        elif any(_canonical(src.get(k)) != _canonical(row.get(k))
                 for k in ('product_id', 'color', 'ram_capacity', 'storage_capacity')):
            errors.append(f'Excel SKU목록: 옵션 불일치 {sku}')

    for row in rdb['inventory_prices']:
        try:
            if not (row['list_price'] > 0 and 0 <= row['sale_price'] <= row['list_price']
                    and row['stock_quantity'] >= 0):
                errors.append(f'가격·재고 범위 오류: {row["sku"]}')
        except (TypeError, ValueError):
            errors.append(f'가격·재고 자료형 오류: {row.get("sku")}')
    # DB에 저장하기 전에 날짜/시간 형식을 검증합니다.
    dates = {
        'products': ('release_date',),
        'inventory_prices': ('updated_at',),
        'sku_sales': ('sales_reference_date',),
        'card_promotions': ('start_date', 'end_date'),
    }
    for table, fields in dates.items():
        for row in rdb[table]:
            for col in fields:
                value = row.get(col)
                if value is None and col == 'updated_at':
                    continue  # DB DEFAULT 사용
                try:
                    if col == 'updated_at':
                        datetime.fromisoformat(str(value))
                    else:
                        date.fromisoformat(str(value)[:10])
                except (ValueError, TypeError):
                    errors.append(f'{table}: {col} 날짜 형식 오류 ({value})')

    for row in rdb['sku_sales']:
        if not isinstance(row.get('sales_quantity_3m'), int) or row['sales_quantity_3m'] < 0:
            errors.append(f'판매량 오류: {row.get("sku")}')
    for row in rdb['card_promotions']:
        try:
            if not (0 <= row['discount_rate'] <= 100 and
                    str(row['start_date']) <= str(row['end_date'])):
                errors.append(f'할인 정책 범위·기간 오류: {row["promotion_id"]}')
        except (TypeError, ValueError):
            errors.append(f'할인 정책 자료형 오류: {row.get("promotion_id")}')

    chunks = []
    for src in extracted['manuals']:
        pid = src['product_id']
        product = products_by_id.get(pid)
        if not product:
            errors.append(f'설명서: 미등록 제품 {pid} (카탈로그를 먼저 넣어야 합니다)')
            continue
        chunk = dict(src)
        chunk['product_name'] = product['product_name']
        chunk['brand'] = product['brand']
        meta = chunk['metadata']
        if not chunk['content'].strip() or meta['page_number'] < 1 or meta['chunk_index'] < 1:
            errors.append(f'설명서 내용 또는 출처 오류: {chunk["chunk_id"]}')
        chunks.append(chunk)

    # 카드할인 관계: 파일이 해당 시트를 포함한 경우에만 대상 정책을 동기화.
    # 관계만 단독 입력할 때도 지원하며, 정책의 모든 대상 삭제는 정책+빈 관계 시트로 지정.
    sync_promotions = set()
    if 'promotion_products' in sales.get('_present_sheets', []):
        sync_promotions.update(r['promotion_id'] for r in rdb['card_promotions'])
        sync_promotions.update(r['promotion_id'] for r in rdb['promotion_products'])

    change_plan = {}
    for table, rows in rdb.items():
        old = existing[table]
        stats = {'insert': [], 'update': [], 'skip': [], 'delete': []}
        for row in rows:
            key = key_for(table, row)
            if key not in old:
                stats['insert'].append(list(key))
            elif not rows_equal(table, row, old[key]):
                stats['update'].append(list(key))
            else:
                stats['skip'].append(list(key))
        if table == 'promotion_products':
            submitted = {key_for(table, r) for r in rows}
            stats['delete'] = [list(k) for k in old if k[0] in sync_promotions and k not in submitted]
        change_plan[table] = stats

    stored_chunks = state['chunks']
    chunk_plan = {'insert': [], 'update': [], 'skip': [], 'delete': [], 'reembed': []}
    latest = {c['chunk_id']: c for c in chunks}
    submitted_products = {c['product_id'] for c in chunks}
    for chunk in chunks:
        cid = chunk['chunk_id']
        previous = stored_chunks.get(cid)
        if not previous:
            chunk_plan['insert'].append(cid)
            chunk_plan['reembed'].append(cid)
        else:
            copied = {k: chunk[k] for k in ('document_id', 'product_id', 'product_name', 'brand', 'content', 'metadata')}
            stored_fields = dict(previous)
            # 저장 metadata의 embedding_model은 관리용 속성이며 원본 PDF metadata와 비교하지 않음.
            stored_fields['metadata'] = {k: v for k, v in previous['metadata'].items()
                                         if k != 'embedding_model'}
            if any(_canonical(copied[k]) != _canonical(stored_fields.get(k)) for k in copied):
                chunk_plan['update'].append(cid)
                if copied['content'] != previous['content']:
                    chunk_plan['reembed'].append(cid)
            else:
                chunk_plan['skip'].append(cid)
    chunk_plan['delete'] = [cid for cid, c in stored_chunks.items()
                            if c['product_id'] in submitted_products and cid not in latest]
    change_plan['document_chunks'] = chunk_plan

    # 제조사 카탈로그에서 상품명이 바뀌면 해당 제품의 기존 청크 복제 필드 동기화
    changed_product_ids = {r['product_id'] for r in rdb['products']}
    sync_chunk_products = [pid for pid in changed_product_ids if any(
        c['product_id'] == pid and (c['product_name'], c['brand']) !=
        (products_by_id[pid]['product_name'], products_by_id[pid]['brand'])
        for c in stored_chunks.values())]

    counts = {table: len(rows) for table, rows in rdb.items()}
    counts['document_chunks'] = len(chunks)
    warnings.append('판매 Excel은 모델별 더미 판매량을 SKU별로 배분한 데이터이며 실판매 기록은 아닙니다.') if sales['inventory_prices'] else None
    warnings.append('PDF 카메라 줌은 광학 수치 우선으로 변환합니다.') if rdb['cameras'] else None
    missing_images = [p['product_id'] for p in rdb['products'] if not p.get('product_image_path')]
    if missing_images:
        warnings.append(f'PDF에 확인 가능한 이미지가 없는 제품 {len(missing_images)}개: ' + ', '.join(missing_images[:10]))
    review = {
        'counts': counts, 'changes': change_plan,
        'sync_promotion_ids': sorted(sync_promotions),
        'sync_chunk_product_ids': sorted(sync_chunk_products),
        'source_files': extracted['source_files'],
        'image_manifest': catalogs.get('images', []),
        'db_fingerprint': state_fingerprint(state),
        'errors': errors[:200], 'warnings': warnings,
        'ready_to_save': not errors,
    }
    return {'rdb': rdb, 'vector_db': {'chunks': chunks}, 'review': review}
