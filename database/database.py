"""ABC Electronics DB 읽기·변경분 저장 (PostgreSQL public + rag, 동일 트랜잭션)."""
import os
from datetime import date, datetime
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from dotenv import load_dotenv

from database.rag import embed_chunks
from database.transform import RDB_TABLES, KEY_COLUMNS, key_for, state_fingerprint

load_dotenv(Path(__file__).resolve().parents[1] / '.env')
DATE_FIELDS = {'release_date', 'sales_reference_date', 'start_date', 'end_date'}


def _connection():
    password = os.getenv('DB_PASSWORD') or os.getenv('POSTGRES_PASSWORD')
    if not password:
        raise RuntimeError('프로젝트 루트 .env에 DB_PASSWORD 또는 POSTGRES_PASSWORD를 설정하세요.')
    return psycopg.connect(
        host=os.getenv('DB_HOST', '127.0.0.1'),
        port=int(os.getenv('DB_PORT', '5433')),
        dbname=os.getenv('DB_NAME', 'ai_sales'),
        user=os.getenv('DB_USER', 'ai_user'),
        password=password, connect_timeout=10, row_factory=dict_row,
    )


def _read_state(cur):
    state = {'rdb': {}, 'chunks': {}}
    for table in RDB_TABLES:
        cur.execute(sql.SQL('SELECT * FROM public.{}').format(sql.Identifier(table)))
        state['rdb'][table] = {tuple(row[k] for k in KEY_COLUMNS[table]): row
                               for row in cur.fetchall()}
    cur.execute('''
        SELECT chunk_id, document_id, product_id, product_name, brand,
               metadata, content, vector_dims(embedding) AS embedding_dim
        FROM rag.document_chunks
    ''')
    state['chunks'] = {r['chunk_id']: r for r in cur.fetchall()}
    return state


def load_state():
    """미리보기용 DB 스냅샷. 데이터 수정 없음."""
    with _connection() as conn:
        with conn.cursor() as cur:
            return _read_state(cur)


def _typed_value(column, value):
    if value is None:
        return None
    if column in DATE_FIELDS and isinstance(value, str):
        return date.fromisoformat(value[:10])
    if column == 'updated_at' and isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def _upsert_rows(cur, table, rows):
    """차이 있는 행만 전달. DB에서도 실제 컬럼 값이 같으면 UPDATE하지 않음."""
    if not rows:
        return
    columns = list(rows[0])
    if any(set(row) != set(columns) for row in rows):
        raise ValueError(f'{table}: 행별 컬럼 구조가 다릅니다.')
    keys = KEY_COLUMNS[table]
    mutable = [col for col in columns if col not in keys]
    compare_fields = [col for col in mutable
                      if not (table == 'inventory_prices' and col == 'updated_at')]
    conflict = sql.SQL('DO NOTHING')
    if mutable:
        updates = sql.SQL(', ').join(sql.SQL('{} = EXCLUDED.{}').format(
            sql.Identifier(col), sql.Identifier(col)) for col in mutable)
        condition = sql.SQL(' OR ').join(sql.SQL('target.{} IS DISTINCT FROM EXCLUDED.{}').format(
            sql.Identifier(col), sql.Identifier(col)) for col in compare_fields)
        conflict = sql.SQL('DO UPDATE SET ') + updates
        if compare_fields:
            conflict += sql.SQL(' WHERE ') + condition
    statement = sql.SQL('''
        INSERT INTO public.{} AS target ({}) VALUES ({})
        ON CONFLICT ({}) {}
    ''').format(
        sql.Identifier(table),
        sql.SQL(', ').join(map(sql.Identifier, columns)),
        sql.SQL(', ').join(sql.Placeholder() for _ in columns),
        sql.SQL(', ').join(map(sql.Identifier, keys)),
        conflict,
    )
    cur.executemany(statement,
                    [tuple(_typed_value(k, row[k]) for k in columns) for row in rows])


def _vector_model_check(state, model):
    """기존 벡터의 임베딩 모델/차원이 다른 경우 혼합 저장 금지."""
    for row in state['chunks'].values():
        old_model = row['metadata'].get('embedding_model')
        if old_model != model:
            raise ValueError(
                f'이미 저장된 벡터의 모델({old_model or "미기록"})과 현재 모델({model})이 다릅니다. '
                '혼합 적재하지 마세요. 이전 벡터를 일괄 재생성하는 별도 작업이 필요합니다.'
            )
    dims = {r['embedding_dim'] for r in state['chunks'].values()}
    if len(dims) > 1:
        raise ValueError(f'기존 벡터 차원이 섞여 있습니다: {dims}')
    return dims.pop() if dims else None


def save_all(preview, embedding_model=None):
    """변경분 저장. 임베딩 실패/DB 실패 시 전체 DB 트랜잭션 롤백."""
    review = preview.get('review', {})
    if not review.get('ready_to_save'):
        raise ValueError('검증에 통과한 미리보기만 저장할 수 있습니다.')
    model = embedding_model or os.getenv('OLLAMA_EMBED_MODEL', 'qwen3-embedding:0.6b')
    plan = review['changes']
    source_chunks = preview['vector_db']['chunks']
    chunk_lookup = {chunk['chunk_id']: chunk for chunk in source_chunks}
    # 바뀐 원문만 임베딩. 파일명·제품명만 변경되면 기존 임베딩 유지.
    embed_ids = plan['document_chunks']['reembed']
    embedded = dict(zip(embed_ids, embed_chunks([chunk_lookup[c] for c in embed_ids], model=model)))
    embedded_dim = len(next(iter(embedded.values()))) if embedded else None
    if embedded_dim and model == 'qwen3-embedding:0.6b' and embedded_dim != 1024:
        raise ValueError(f'Qwen3 0.6B의 임베딩 차원이 예상과 다릅니다: {embedded_dim}')

    with _connection() as conn:
        with conn.cursor() as cur:
            # 동일 PC에서 관리자 화면을 동시에 두 번 눌러 저장하는 상황 예방
            cur.execute('SELECT pg_advisory_xact_lock(2026, 1104)')
            state = _read_state(cur)
            if state_fingerprint(state) != review['db_fingerprint']:
                raise RuntimeError('미리보기 이후 DB 데이터가 변경됐습니다. 파일을 다시 분석하세요.')
            if source_chunks:
                known_dim = _vector_model_check(state, model)
                if known_dim and embedded_dim and known_dim != embedded_dim:
                    raise ValueError(f'임베딩 차원 충돌: 기존 {known_dim}, 신규 {embedded_dim}')

            for table in RDB_TABLES:
                if table == 'promotion_products':
                    continue
                changes = plan[table]
                changed_keys = {tuple(k) for k in changes['insert'] + changes['update']}
                _upsert_rows(cur, table,
                             [row for row in preview['rdb'][table]
                              if key_for(table, row) in changed_keys])

            # 관계 시트에서 수정 대상 정책만 동기화, 나머지 할인 대상은 유지
            for promotion_id, product_id in plan['promotion_products']['delete']:
                cur.execute('''DELETE FROM public.promotion_products
                               WHERE promotion_id = %s AND product_id = %s''',
                            (promotion_id, product_id))
            relation_changes = plan['promotion_products']
            changed_rel = {tuple(k) for k in relation_changes['insert'] + relation_changes['update']}
            _upsert_rows(cur, 'promotion_products',
                         [r for r in preview['rdb']['promotion_products']
                          if key_for('promotion_products', r) in changed_rel])

            # RDB에서 제품명/브랜드를 재조회하여 rag에 복사
            product_ids = sorted({c['product_id'] for c in source_chunks}
                                 | set(review.get('sync_chunk_product_ids', [])))
            names = {}
            if product_ids:
                cur.execute('''SELECT product_id, product_name, brand
                               FROM public.products WHERE product_id = ANY(%s)''', (product_ids,))
                names = {row['product_id']: row for row in cur.fetchall()}
                if set(names) != set(product_ids):
                    raise ValueError('RAG 저장에 필요한 제품 ID가 RDB에 없습니다.')

            # 설명서를 새로 가져온 상품에서 더 이상 존재하지 않는 청크만 제거
            for chunk_id in plan['document_chunks']['delete']:
                cur.execute('DELETE FROM rag.document_chunks WHERE chunk_id = %s', (chunk_id,))

            changes = plan['document_chunks']
            for cid in changes['insert'] + changes['update']:
                chunk = chunk_lookup[cid]
                product = names[chunk['product_id']]
                meta = {**chunk['metadata'], 'embedding_model': model}
                if cid in embedded:
                    vec = embedded[cid]
                    vector_text = '[' + ','.join(str(v) for v in vec) + ']'
                    cur.execute('''
                        INSERT INTO rag.document_chunks
                        (chunk_id, document_id, product_id, product_name, brand,
                         metadata, content, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)
                        ON CONFLICT (chunk_id) DO UPDATE SET
                          document_id=EXCLUDED.document_id,
                          product_id=EXCLUDED.product_id,
                          product_name=EXCLUDED.product_name,
                          brand=EXCLUDED.brand, metadata=EXCLUDED.metadata,
                          content=EXCLUDED.content, embedding=EXCLUDED.embedding
                    ''', (cid, chunk['document_id'], chunk['product_id'],
                          product['product_name'], product['brand'], Jsonb(meta),
                          chunk['content'], vector_text))
                else:
                    # 원문이 같으면 기존 임베딩 그대로 두고 출처/복제 필드만 수정
                    cur.execute('''
                        UPDATE rag.document_chunks SET
                          document_id=%s, product_name=%s, brand=%s,
                          metadata=%s, content=%s
                        WHERE chunk_id=%s
                    ''', (chunk['document_id'], product['product_name'], product['brand'],
                          Jsonb(meta), chunk['content'], cid))

            # 이번에 카탈로그가 수정된 제품의 이전 설명서 복제정보도 맞춤
            for pid in review.get('sync_chunk_product_ids', []):
                cur.execute('''UPDATE rag.document_chunks
                               SET product_name=%s, brand=%s
                               WHERE product_id=%s''',
                            (names[pid]['product_name'], names[pid]['brand'], pid))
        # 성공 시 COMMIT, 예외 시 ROLLBACK
    return {'changes': {t: {action: len(p.get(action, []))
                           for action in ('insert', 'update', 'skip', 'delete')}
                        for t, p in plan.items()},
            'embedded_chunks': len(embedded),
            'embedding_dim': embedded_dim or (known_dim if source_chunks else None),
            'embedding_model': model}
