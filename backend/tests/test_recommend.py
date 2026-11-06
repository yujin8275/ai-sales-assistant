import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.models import ProductFilters, RecommendFilters, RecommendRequest, QuoteItem
from backend.app.rag import RagTool
from backend.app.recommendation import prepare_candidates, recommend
from backend.app.tools import QuoteTool
from backend.tests.test_quote import Repo, variant, policy


class SearchRepo(Repo):
    def search_variants(self, filters):
        return [r for r in self.rows if (filters.scope_product_ids is None or r["product_id"] in filters.scope_product_ids)
                and (not filters.ram_gb or r["ram_gb"] == filters.ram_gb)]

    def product(self, pid):
        return dict(product_id=pid, product_name=pid, brand="Test", image_url=None,
                    specs=dict(processor=None, weight_g=None, battery_mah=None, display_inches=None, cameras=[]))

    def sales(self, ids):
        return [{"product_id": pid, "sales_quantity_3m": 100 if pid == "B" else 10,
                 "sales_reference_date": None} for pid in ids]


@pytest.mark.parametrize("filters", [
    {"quantity": True}, {"ram_gb": 1.5}, {"brands": None}, {"purpose": None},
    {"scope_product_ids": None}, {"storage_gb": 128, "min_storage_gb": 128},
    {"min_display_inches": float("inf")}, {"min_display_inches": True},
    {"budget": {"amount": 0}}, {"unknown": 1},
])
def test_filters_reject_invalid_inputs(filters):
    with pytest.raises(ValueError):
        RecommendFilters(**filters)


def test_empty_scope_stays_empty():
    candidates, _, _ = prepare_candidates(SearchRepo(), RecommendFilters(scope_product_ids=[]))
    assert candidates == []


def test_budget_uses_discount_and_does_not_prune_sale_price():
    repo = SearchRepo(policies=[policy()])
    candidates, _, _ = prepare_candidates(repo, RecommendFilters(card_company="카드",
        budget={"amount": 51}, quantity=1))
    assert candidates[0]["representative"]["sale_price"] == 101
    assert candidates[0]["price"]["total"] == 50


def test_total_budget_and_duplicate_options():
    repo = SearchRepo([variant("A", price=100), variant("B", price=200, ram=8)])
    result, _, _ = prepare_candidates(repo, RecommendFilters(quantity=2,
        budget={"amount": 300, "scope": "TOTAL"}))
    assert len(result) == 1
    assert [v["sku"] for v in result[0]["variants"]] == ["A"]


def test_only_eligible_ram_sets_starting_price():
    result, _, _ = prepare_candidates(SearchRepo([variant("A", price=100), variant("B", price=200, ram=8)]),
                                      RecommendFilters(ram_gb=8))
    assert result[0]["representative"]["sale_price"] == 200


def test_shortage_excluded_but_reported():
    result, _, unavailable = prepare_candidates(SearchRepo([variant(stock=1)]), RecommendFilters(quantity=2))
    assert result == []
    assert unavailable[0]["reason"] == "INSUFFICIENT_STOCK"


def test_no_purpose_orders_sales_before_price(monkeypatch):
    repo = SearchRepo([variant() | {"product_id": "A"}, variant("B", price=500) | {"product_id": "B"}])
    monkeypatch.setattr("backend.app.recommendation.read_once_retry", lambda engine, operation: operation(repo))
    result = asyncio.run(recommend(None, RecommendRequest(request_id=uuid4())))
    assert [r["product_id"] for r in result.data["recommendations"]] == ["B", "A"]
    assert result.evidence_status == "NOT_USED"


def test_no_matches_does_not_call_model(monkeypatch):
    monkeypatch.setattr("backend.app.recommendation.read_once_retry", lambda engine, operation:
        operation(SearchRepo([])))
    result = asyncio.run(recommend(None, RecommendRequest(request_id=uuid4())))
    assert result.status == "NO_MATCH"


def test_empty_document_scope_does_not_embed():
    result = asyncio.run(RagTool(None, object()).search_product_documents("배터리", []))
    assert result.data == {"hits": [], "has_evidence": False}


def test_suitability_precedes_sales_and_sources_only_for_selected(monkeypatch):
    repo = SearchRepo([variant() | {"product_id": "A"}, variant("B") | {"product_id": "B"}])
    monkeypatch.setattr("backend.app.recommendation.read_once_retry", lambda engine, operation: operation(repo))
    hit = {"product_id": "A", "chunk_id": "c", "document_id": "d", "content": "배터리 설명",
           "metadata": {"source_file": "manual.pdf", "page_number": 1}, "distance": .1}

    async def search(*args):
        from backend.app.models import ToolResult
        return ToolResult(status="OK", data={"hits": [hit], "has_evidence": True})

    class Model:
        async def evaluate(self, *args):
            return {"A": 3, "B": 1}

    monkeypatch.setattr(RagTool, "search_product_documents", search)
    result = asyncio.run(recommend(None, RecommendRequest(request_id=uuid4(), limit=1,
        filters={"purpose": "배터리"}), Model()))
    assert result.data["recommendations"][0]["product_id"] == "A"
    assert result.sources[0]["source_file"] == "manual.pdf"
    assert "chunk_id" not in result.sources[0]
    assert result.data["recommendations"][0]["reasons"][1]["source_ids"] == ["source-1"]


def test_api_recommend_and_null_filters(monkeypatch):
    from backend.app.models import Response
    async def run(engine, body):
        return Response(request_id=body.request_id, status="NO_MATCH", message="없음")
    monkeypatch.setattr("backend.app.main.recommend", run)
    app.state.engine = object()
    client = TestClient(app)
    assert client.post("/recommend", json={"request_id": str(uuid4())}).status_code == 200
    assert client.post("/recommend", json={"request_id": str(uuid4()), "filters": None}).status_code == 422


def test_model_failure_returns_error_without_fallback(monkeypatch):
    from backend.app.tools import BusinessError
    async def fail(engine, body):
        raise BusinessError("MODEL_ERROR", "추천 평가 실패", 503)
    monkeypatch.setattr("backend.app.main.recommend", fail)
    app.state.engine = object()
    response = TestClient(app).post("/recommend", json={"request_id": str(uuid4())})
    assert response.status_code == 503
    assert response.json()["data"] is None
    assert response.json()["error"]["code"] == "MODEL_ERROR"


@pytest.mark.parametrize("vector", [[1.0], [float("nan")] * 1024, [0.0] * 1024])
def test_malformed_embedding_rejected(monkeypatch, vector):
    from backend.app.rag import OllamaClient
    from backend.app.tools import BusinessError
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): return self
        def raise_for_status(self): pass
        def json(self): return {"embeddings": [vector]}
    monkeypatch.setattr("backend.app.rag.httpx.AsyncClient", Client)
    with pytest.raises(BusinessError):
        asyncio.run(OllamaClient().embed("배터리"))


@pytest.mark.parametrize("evaluations", [
    {"invented":3},
    {},
    {"A":True},
    {"A":4},
])
def test_invented_duplicate_or_invalid_evaluations_rejected(monkeypatch, evaluations):
    import json
    from backend.app.rag import OllamaClient
    from backend.app.tools import BusinessError
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): return self
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": json.dumps(evaluations)}}
    monkeypatch.setattr("backend.app.rag.httpx.AsyncClient", Client)
    candidate = {"product": {"product_id": "A", "specs": {}},
                 "representative": {"ram_gb": 4, "storage_gb": 128}}
    with pytest.raises(BusinessError):
        asyncio.run(OllamaClient().evaluate("배터리", [candidate], []))


def test_all_candidates_evaluated_in_bounded_batches(monkeypatch):
    import json
    from backend.app.rag import OllamaClient
    sizes=[]
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,*args,**kwargs):
            request=kwargs['json'];ids=request['format']['required']
            products=json.loads(request['messages'][-1]['content'])['products']
            assert ids==[p['product_id'] for p in products]
            sizes.append(len(ids));self.result={pid:2 for pid in ids}
            return self
        def raise_for_status(self):pass
        def json(self):return {'message':{'content':json.dumps(self.result)}}
    monkeypatch.setattr('backend.app.rag.httpx.AsyncClient',Client)
    candidates=[{'product':{'product_id':str(i),'specs':{}},'representative':{'ram_gb':4,'storage_gb':128}} for i in range(11)]
    result=asyncio.run(OllamaClient().evaluate('배터리',candidates,[]))
    assert sizes==[5,5,1] and result=={str(i):2 for i in range(11)}
