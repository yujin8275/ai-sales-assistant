
-- ABC Electronics
-- Vector DB 테이블 생성
-- 01_create_rdb.sql 실행 후 사용

BEGIN;

-- pgvector 확장 활성화
CREATE EXTENSION IF NOT EXISTS vector;

-- Vector DB 전용 스키마
CREATE SCHEMA IF NOT EXISTS rag;

-- 문서 청크 테이블
CREATE TABLE rag.document_chunks (
    chunk_id     VARCHAR(64) PRIMARY KEY,

    -- 문서 출처 식별자
    document_id  VARCHAR(40) NOT NULL,

    -- RDB 상품과 연결
    product_id   VARCHAR(40) NOT NULL
        REFERENCES public.products(product_id),

    -- RDB products에서 복사
    product_name VARCHAR(100) NOT NULL,
    brand        VARCHAR(50) NOT NULL,

    -- 문서 출처 세부정보
    metadata     JSONB NOT NULL,

    -- 제품 설명 원문
    content      TEXT NOT NULL
        CHECK (length(btrim(content)) > 0),

    -- 임베딩 벡터
    embedding    VECTOR NOT NULL,

    -- metadata 구조 검증
    CONSTRAINT chk_chunk_metadata CHECK (
        jsonb_typeof(metadata) = 'object'

        AND metadata ? 'source_file'
        AND jsonb_typeof(
            metadata -> 'source_file'
        ) = 'string'
        AND length(
            btrim(metadata ->> 'source_file')
        ) > 0

        AND metadata ? 'page_number'
        AND jsonb_typeof(
            metadata -> 'page_number'
        ) = 'number'
        AND (
            metadata ->> 'page_number'
        ) ~ '^[1-9][0-9]*$'

        AND metadata ? 'chunk_index'
        AND jsonb_typeof(
            metadata -> 'chunk_index'
        ) = 'number'
        AND (
            metadata ->> 'chunk_index'
        ) ~ '^[1-9][0-9]*$'
    )
);

-- 상품 ID 기반 검색
CREATE INDEX idx_chunks_product_id
    ON rag.document_chunks(product_id);

-- 문서 ID 기반 검색
CREATE INDEX idx_chunks_document_id
    ON rag.document_chunks(document_id);

COMMIT;
