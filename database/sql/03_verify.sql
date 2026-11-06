
-- ABC Electronics
-- 테이블 생성 검증

-- 1. 스키마별 테이블 개수
SELECT
    table_schema,
    COUNT(*) AS table_count
FROM information_schema.tables
WHERE table_schema IN ('public', 'rag')
  AND table_type = 'BASE TABLE'
GROUP BY table_schema
ORDER BY table_schema;


-- 2. 생성된 테이블 목록
SELECT
    table_schema,
    table_name
FROM information_schema.tables
WHERE table_schema IN ('public', 'rag')
  AND table_type = 'BASE TABLE'
ORDER BY table_schema, table_name;


-- 3. pgvector 확장 확인
SELECT
    extname,
    extversion
FROM pg_extension
WHERE extname = 'vector';


-- 4. Vector DB 컬럼 확인
SELECT
    column_name,
    data_type,
    udt_name
FROM information_schema.columns
WHERE table_schema = 'rag'
  AND table_name = 'document_chunks'
ORDER BY ordinal_position;


-- 5. Vector DB FK 확인
SELECT
    c.conname AS foreign_key,
    c.conrelid::regclass AS from_table,
    c.confrelid::regclass AS to_table
FROM pg_constraint c
WHERE c.contype = 'f'
  AND c.conrelid = 'rag.document_chunks'::regclass;


-- 6. RDB에 문서 출처 테이블이 없는지 확인
SELECT NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name = 'source_documents'
) AS no_source_documents_in_rdb;


-- 7. products에 출처 컬럼이 없는지 확인
SELECT NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'products'
      AND column_name = 'catalog_document_id'
) AS no_catalog_source_column_in_rdb;


-- 8. updated_at 트리거 확인
SELECT
    t.tgname AS trigger_name,
    t.tgenabled AS enabled
FROM pg_trigger t
WHERE t.tgrelid = 'public.inventory_prices'::regclass
  AND t.tgname = 'trg_inventory_prices_updated_at'
  AND NOT t.tgisinternal;
