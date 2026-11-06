"""공통 DB 접근 모듈. Tool은 이 모듈을 통해서만 DB를 조회한다."""
import os
from pathlib import PurePosixPath
from contextlib import contextmanager

from psycopg import OperationalError

from sqlalchemy import URL, create_engine, text
from sqlalchemy.exc import DBAPIError


def make_engine():
    password = os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD")
    if not password:
        raise RuntimeError("DB_PASSWORD 또는 POSTGRES_PASSWORD가 필요합니다.")
    url = URL.create("postgresql+psycopg", username=os.getenv("DB_USER", "ai_user"),
                     password=password, host=os.getenv("DB_HOST", "db"),
                     port=int(os.getenv("DB_PORT", "5432")),
                     database=os.getenv("DB_NAME", "ai_sales"))
    return create_engine(url, pool_size=5, max_overflow=5, pool_pre_ping=True,
                         pool_timeout=5, connect_args={"connect_timeout": 5})


@contextmanager
def snapshot(engine):
    # 한 견적의 품목/가격/정책을 같은 읽기 스냅샷에서 확인한다. 재고 예약은 하지 않는다.
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text("SET LOCAL statement_timeout = '10000ms'"))
            yield Repository(conn)


def read_once_retry(engine, operation):
    for attempt in range(2):
        try:
            with snapshot(engine) as repo:
                return operation(repo)
        except DBAPIError as exc:
            # 재실행 가능한 읽기만 재시도한다. SQL/데이터 오류는 반복하지 않는다.
            state = getattr(exc.orig, "sqlstate", "") or ""
            transient = (exc.connection_invalidated or state.startswith("08") or
                         state in ("57P01", "57P02", "57P03") or
                         (not state and isinstance(exc.orig, OperationalError)))
            if attempt or not transient:
                raise


VARIANTS_SQL = """
SELECT v.sku, v.product_id, p.product_name, p.brand, p.product_image_path,
       v.color, v.ram_capacity AS ram_gb, v.storage_capacity AS storage_gb,
       i.sale_price, i.stock_quantity, i.updated_at AS price_updated_at
FROM public.product_variants v
JOIN public.products p ON p.product_id=v.product_id
LEFT JOIN public.inventory_prices i ON i.sku=v.sku
"""


class Repository:
    def __init__(self, connection):
        self.connection = connection

    def variants(self, skus):
        return [dict(r) for r in self.connection.execute(text(
            VARIANTS_SQL + " WHERE v.sku = ANY(:skus) ORDER BY v.sku"),
            {"skus": list(skus)}).mappings()]

    def product_variants(self, product_id):
        return [dict(r) for r in self.connection.execute(text(
            VARIANTS_SQL + " WHERE v.product_id=:product_id ORDER BY i.sale_price, v.sku"),
            {"product_id": product_id}).mappings()]

    def product(self, product_id):
        row = self.connection.execute(text("""
          SELECT p.product_id, p.product_name, p.brand, p.product_image_path,
                 s.processor, s.weight AS weight_g, s.battery_capacity AS battery_mah,
                 d.display_size AS display_inches
          FROM public.products p
          LEFT JOIN public.product_specs s USING(product_id)
          LEFT JOIN public.display_specs d USING(product_id)
          WHERE p.product_id=:product_id
        """), {"product_id": product_id}).mappings().first()
        if row is None:
            return None
        result = dict(row)
        cameras = self.connection.execute(text("""
          SELECT camera_type, resolution_mp, aperture, max_zoom, ois
          FROM public.cameras WHERE product_id=:product_id ORDER BY camera_id
        """), {"product_id": product_id}).mappings()
        result["specs"] = {key: result.pop(key) for key in
                           ("processor", "weight_g", "battery_mah", "display_inches")}
        result["specs"]["cameras"] = [dict(r) for r in cameras]
        # 내부 파일 경로를 공개 URL로 사용하지 않는다. 이미지 제공은 UI 단계에서 연결한다.
        path = result.pop("product_image_path", None)
        parsed = PurePosixPath(path) if path else None
        result["image_url"] = "/images/" + "/".join(parsed.parts[1:]) if parsed and parsed.parts[0] == "product_images" and ".." not in parsed.parts else None
        return result

    def promotions(self, card_company):
        return [dict(r) for r in self.connection.execute(text("""
          SELECT c.*, ARRAY(SELECT pp.product_id FROM public.promotion_products pp
                            WHERE pp.promotion_id=c.promotion_id) AS product_ids
          FROM public.card_promotions c WHERE c.card_company=:company
        """), {"company": card_company}).mappings()]

    def check_database(self):
        self.connection.execute(text("SELECT 1 FROM public.inventory_prices LIMIT 1"))

    def search_variants(self, filters):
        clauses, params = [], {}
        for field, column in (("brands", "p.brand"), ("colors", "v.color"),
                              ("scope_product_ids", "p.product_id")):
            value = getattr(filters, field)
            if value is not None and (value or field == "scope_product_ids"):
                clauses.append(f"{column} = ANY(:{field})")
                params[field] = value
        for field, column, operator in (
            ("ram_gb", "v.ram_capacity", "="), ("storage_gb", "v.storage_capacity", "="),
            ("min_storage_gb", "v.storage_capacity", ">="),
            ("min_display_inches", "d.display_size", ">="),
            ("max_weight_g", "s.weight", "<="),
            ("min_battery_mah", "s.battery_capacity", ">=")):
            value = getattr(filters, field)
            if value is not None:
                clauses.append(f"{column} {operator} :{field}")
                params[field] = value
        query = VARIANTS_SQL + """
          LEFT JOIN public.product_specs s ON s.product_id=p.product_id
          LEFT JOIN public.display_specs d ON d.product_id=p.product_id
        """
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        return [dict(r) for r in self.connection.execute(text(query + " ORDER BY p.product_id, v.sku"), params).mappings()]

    def sales(self, product_ids):
        return [dict(r) for r in self.connection.execute(text("""
          SELECT v.product_id, COALESCE(SUM(s.sales_quantity_3m),0) AS sales_quantity_3m,
                   MAX(s.sales_reference_date) AS sales_reference_date,
                   COUNT(DISTINCT s.sales_reference_date) AS reference_date_count
          FROM public.product_variants v LEFT JOIN public.sku_sales s USING(sku)
          WHERE v.product_id = ANY(:ids) GROUP BY v.product_id
        """), {"ids": product_ids}).mappings()]

    def catalogue(self):
        products = self.connection.execute(text("SELECT product_id,product_name,brand FROM public.products ORDER BY product_id")).mappings()
        return [dict(row) for row in products]

    def document_hits(self, vector, product_ids, top_k, max_distance, model):
        # 상품 범위·모델·차원을 먼저 제한하고 바인딩한 값으로 검색한다.
        rows = self.connection.execute(text("""
          WITH eligible AS MATERIALIZED (
            SELECT * FROM rag.document_chunks
            WHERE product_id = ANY(:ids) AND vector_dims(embedding)=1024
              AND metadata->>'embedding_model' = :model
          ), ranked AS (
            SELECT product_id, chunk_id, document_id, content, metadata,
                   embedding <=> CAST(:vector AS vector) AS distance,
                   ROW_NUMBER() OVER (PARTITION BY product_id
                     ORDER BY embedding <=> CAST(:vector AS vector), chunk_id) AS position
            FROM eligible
          )
          SELECT product_id, chunk_id, document_id, content, metadata, distance
          FROM ranked WHERE position<=:top_k AND distance<=:threshold
          ORDER BY product_id, distance, chunk_id
        """), {"ids": product_ids, "vector": vector, "model": model,
                "top_k": top_k, "threshold": max_distance}).mappings()
        return [dict(r) for r in rows]
