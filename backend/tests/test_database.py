"""명시적으로 요청할 때만 기존 DB에 읽기 전용 통합 테스트를 실행한다."""
import os

import pytest

from backend.app.models import QuoteItem
from backend.app.models import RecommendFilters
from backend.app.recommendation import prepare_candidates
from backend.app.repository import make_engine, read_once_retry
from backend.app.tools import ProductTool, QuoteTool

pytestmark = pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="DB 통합 테스트 별도 실행")


def test_existing_sku_and_readonly_quote():
    engine = make_engine()
    try:
        def check(repo):
            result = ProductTool(repo).get_product_details("RM-15C", storage_gb=128)
            assert result.status == "OK"
            assert {4, 6, 8} <= {v["ram_gb"] for v in result.data["variants"]}
            rows = repo.variants(["RM-15C-BK-4-128"])
            row = rows[0]
            result = QuoteTool(repo).calculate_quote([QuoteItem(sku=row["sku"], quantity=1)])
            assert result.status == "OK"
            assert result.data["quote"]["total"] == row["sale_price"]
            shortage = QuoteTool(repo).calculate_quote([
                QuoteItem(sku=row["sku"], quantity=row["stock_quantity"] + 1)])
            assert shortage.status == "OUT_OF_STOCK"
            assert "quote" not in shortage.data
        read_once_retry(engine, check)
    finally:
        engine.dispose()


def test_search_existing_filters_and_empty_scope():
    engine = make_engine()
    try:
        def check(repo):
            filters = RecommendFilters(scope_product_ids=["RM-15C"], storage_gb=128, ram_gb=8,
                                       quantity=1, budget={"amount": 500000})
            candidates, _, _ = prepare_candidates(repo, filters)
            assert len(candidates) == 1
            assert all(v["ram_gb"] == 8 and v["storage_gb"] == 128 for v in candidates[0]["variants"])
            empty, _, _ = prepare_candidates(repo, RecommendFilters(scope_product_ids=[]))
            assert empty == []
            assert repo.sales(["RM-15C"])[0]["sales_quantity_3m"] >= 0
        read_once_retry(engine, check)
    finally:
        engine.dispose()
