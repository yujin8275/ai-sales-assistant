from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.models import QuoteItem, QuoteRequest
from backend.app.tools import BusinessError, ProductTool, QuoteTool

NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)


def variant(sku="A", price=101, stock=10, ram=4):
    return dict(sku=sku, product_id="P", product_name="Phone", color="검정",
                ram_gb=ram, storage_gb=128, sale_price=price,
                stock_quantity=stock, price_updated_at=NOW)


class Repo:
    def __init__(self, rows=None, policies=None):
        self.rows = rows if rows is not None else [variant()]
        self.policies = policies or []

    def variants(self, skus):
        return [r for r in self.rows if r["sku"] in skus]

    def promotions(self, company):
        return self.policies

    def product(self, product_id):
        return {"product_id": "P"} if product_id == "P" else None

    def product_variants(self, product_id):
        return self.rows


def policy(**overrides):
    return dict(promotion_id="CARD", discount_rate=Decimal("50.00"),
                start_date=date(2026, 1, 1), end_date=date(2026, 12, 31),
                applies_to_all=True, is_active=True, product_ids=[]) | overrides


def calculate(repo=None, items=None, company=None):
    return QuoteTool(repo or Repo(), NOW).calculate_quote(
        items or [QuoteItem(sku="A", quantity=3)], company)


def test_subtotal_rounding_and_no_added_tax():
    quote = calculate(Repo(policies=[policy()]), company="카드").data["quote"]
    assert (quote["subtotal"], quote["discount_amount"], quote["total"]) == (303, 152, 151)
    assert "tax_status" not in quote and "tax_notice" not in quote


def test_duplicates_are_merged_before_discount():
    result = calculate(Repo(policies=[policy()]),
                       [QuoteItem(sku="A", quantity=1)] * 3, "카드")
    assert len(result.data["quote"]["items"]) == 1
    assert result.data["quote"]["discount_amount"] == 152


def test_partial_shortage_prevents_entire_quote():
    result = calculate(Repo([variant(), variant("B", stock=0)]),
                       [QuoteItem(sku="A", quantity=1), QuoteItem(sku="B", quantity=2)])
    assert result.status == "OUT_OF_STOCK"
    assert "quote" not in result.data
    assert result.data["stock_issues"][0]["shortage_quantity"] == 2


def test_missing_and_shortage_both_reported():
    result = calculate(Repo([variant(stock=0)]),
                       [QuoteItem(sku="A", quantity=2), QuoteItem(sku="X", quantity=1)])
    assert result.status == "NOT_FOUND"
    assert result.data["missing_skus"] == ["X"]
    assert result.data["stock_issues"]
    assert "quote" not in result.data


@pytest.mark.parametrize("overrides,expected", [
    ({"is_active": False}, "INACTIVE"),
    ({"start_date": date(2027, 1, 1)}, "INACTIVE"),
    ({"end_date": date(2025, 1, 1)}, "EXPIRED"),
    ({"applies_to_all": False}, "NOT_ELIGIBLE"),
])
def test_unavailable_discount(overrides, expected):
    line = calculate(Repo(policies=[policy(**overrides)]), company="카드").data["quote"]["items"][0]
    assert line["promotion_status"] == expected
    assert line["discount_amount"] == 0


def test_duplicate_policy_is_error():
    with pytest.raises(BusinessError, match="정책"):
        calculate(Repo(policies=[policy(), policy()]), company="카드")


@pytest.mark.parametrize("quantity", [True, 1.5, "3", 0, -1, 2_147_483_648])
def test_invalid_quantities(quantity):
    with pytest.raises(ValueError):
        QuoteItem(sku="A", quantity=quantity)


def test_duplicate_quantity_overflow():
    with pytest.raises(BusinessError):
        calculate(items=[QuoteItem(sku="A", quantity=2_147_483_647), QuoteItem(sku="A", quantity=1)])


def test_amount_overflow():
    with pytest.raises(BusinessError):
        calculate(Repo([variant(price=9_007_199_254_740_991)]))


def test_price_missing_is_not_free():
    with pytest.raises(BusinessError):
        calculate(Repo([variant(price=None)]))


def test_options_keep_ram_and_stock_separate():
    result = ProductTool(Repo([variant(), variant("B", ram=8, stock=0)])).get_product_details("P")
    assert [v["ram_gb"] for v in result.data["variants"]] == [4, 8]
    assert result.data["variants"][1]["availability"] == "OUT_OF_STOCK"


def test_candidate_prices_are_not_cart_total():
    tool = QuoteTool(Repo([variant(), variant("B", stock=0)]), NOW)
    result = tool.price_candidates([QuoteItem(sku="A", quantity=1), QuoteItem(sku="B", quantity=1)])
    assert len(result.data["prices"]) == 1
    assert result.issues[0]["sku"] == "B"


def test_korean_date_boundary():
    time = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)
    tool = QuoteTool(Repo(policies=[policy(start_date=date(2026, 11, 5))]), time)
    assert tool.calculate_quote([QuoteItem(sku="A", quantity=1)], "카드").data["quote"]["discount_amount"] == 51


def test_api_and_common_validation_response(monkeypatch):
    monkeypatch.setattr("backend.app.main.read_once_retry", lambda engine, operation: operation(Repo()))
    app.state.engine = object()
    client = TestClient(app, raise_server_exceptions=True)
    request_id = str(uuid4())
    response = client.post("/quote", json={"request_id": request_id,
        "items": [{"sku": "A", "quantity": 3}]})
    assert response.status_code == 200
    assert response.json()["data"]["quote"]["total"] == 303
    assert response.json()["session_id"] is None
    invalid = client.post("/quote", json={"request_id": request_id,
        "items": [{"sku": "A", "quantity": True}]})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_INPUT"
    assert invalid.json()["request_id"] == request_id


def test_extra_fields_and_null_items_rejected():
    for payload in ({"items": None}, {"items": []},
                    {"items": [{"sku": "A", "quantity": 1}], "session_id": str(uuid4())}):
        with pytest.raises(ValueError):
            QuoteRequest(request_id=uuid4(), **payload)


def test_known_card_without_policy():
    line = calculate(company="등록되지 않은 카드").data["quote"]["items"][0]
    assert line["promotion_status"] == "NOT_FOUND"
    assert line["total"] == 303


def test_multi_item_sum_and_round_per_line():
    quote = calculate(Repo([variant(), variant("B")], [policy()]),
        [QuoteItem(sku="A", quantity=1), QuoteItem(sku="B", quantity=1)], "카드").data["quote"]
    assert quote["discount_amount"] == 102
    assert quote["total"] == 100
