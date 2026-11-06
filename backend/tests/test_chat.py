import asyncio
import copy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.chat import ChatFlow, ChatService, resolve_targets
from backend.app.main import app
from backend.app.models import ChatAction, ChatRequest, Response
from backend.app.tools import BusinessError
from backend.tests.test_quote import Repo, variant


def body(message="추천해줘", session_id=None):
    return ChatRequest(session_id=session_id or uuid4(), request_id=uuid4(), message=message)


class Model:
    async def finalize(self, result): return result


def graph(body, state=None, action=None, lists=None):
    return {"body": body, "state": state or {}, "context": {"lists": lists or []},
            "action": action or ChatAction(intent="UNKNOWN"), "emit": lambda *a: None}


def test_latest_ordinal_and_ambiguous_previous():
    context = {"lists": [{"items": [{"position": 2, "product_id": "P"}]}]}
    assert resolve_targets(ChatAction(intent="QUOTE"), context, "두 번째로") == ["P"]
    context["lists"].append({"items": []})
    assert resolve_targets(ChatAction(intent="QUOTE"), context, "아까 거") is None


def test_multiple_ram_options_require_selection(monkeypatch):
    class DataRepo(Repo):
        def product(self, pid): return {"product_id": pid}
        def product_variants(self, pid): return [variant(), variant("B", ram=8, stock=0)]
    monkeypatch.setattr("backend.app.chat.read_once_retry", lambda engine, operation: operation(DataRepo()))
    state = {"constraints": {"quantity": 3}, "selected_product_ids": ["P"]}
    result = asyncio.run(ChatFlow(None, Model()).execute(graph(body(), state, ChatAction(intent="QUOTE"))))
    assert result["result"].status == "NEED_INPUT"
    assert len(result["result"].data["variants"]) == 2
    assert not result["state"].get("selected_items")


class MemorySessions:
    def __init__(self):
        self.records, self.state, self.completed = {}, {}, []
    def register(self, b):
        old = self.records.get(b.request_id)
        if old and old[0] != b.message: raise BusinessError("REQUEST_CONFLICT", "conflict", 409)
        if old: return old[1]
        self.records[b.request_id] = (b.message, None)
    def load(self, b):
        return {"state": copy.deepcopy(self.state), "version": 0, "messages": [], "lists": []}
    def finish(self, b, version, state, result):
        self.state = state
        self.completed.append(b.message)
        self.records[b.request_id] = (b.message, result.model_dump(mode="json"))
    def fail(self, b, result):
        self.records[b.request_id] = (b.message, result.model_dump(mode="json"))


class FakeGraph:
    def __init__(self, fail=False, delay=.01): self.calls, self.fail, self.delay = [], fail, delay
    async def ainvoke(self, graph):
        self.calls.append(graph["body"].message)
        await asyncio.sleep(self.delay)
        if self.fail: raise BusinessError("MODEL_ERROR", "실패", 503)
        return {"state": {"count": graph["context"]["state"].get("count", 0)+1},
            "result": Response(request_id=graph["body"].request_id, session_id=graph["body"].session_id,
                               status="OK", message="완료")}


def test_same_session_fifo_and_inflight_deduplication():
    async def run():
        store, runner = MemorySessions(), FakeGraph()
        service = ChatService(None, store, SimpleNamespace(graph=runner))
        first = body("첫 요청")
        j1, _ = await service.submit(first)
        duplicate, _ = await service.submit(first)
        j2, _ = await service.submit(body("두 번째 요청", first.session_id))
        assert j1 is duplicate
        await asyncio.gather(j1.task, j2.task)
        assert runner.calls == ["첫 요청", "두 번째 요청"]
        assert store.state == {"count": 2}
        _, cached = await service.submit(first)
        assert cached.status == "OK"
    asyncio.run(run())


def test_model_error_preserves_previous_state():
    async def run():
        store = MemorySessions()
        store.state = {"last_quote": {"total": 100}}
        service = ChatService(None, store, SimpleNamespace(graph=FakeGraph(fail=True)))
        job, _ = await service.submit(body())
        result = await job.task
        assert result.error["code"] == "MODEL_ERROR"
        assert store.state == {"last_quote": {"total": 100}}
        assert store.completed == []
    asyncio.run(run())


def test_timeout_includes_queue_wait():
    async def run():
        store = MemorySessions()
        service = ChatService(None, store, SimpleNamespace(graph=FakeGraph(delay=.2)), timeout=.03)
        first = body()
        j1, _ = await service.submit(first)
        j2, _ = await service.submit(body("다음", first.session_id))
        results = await asyncio.gather(j1.task, j2.task)
        assert all(r.error["code"] == "REQUEST_TIMEOUT" for r in results)
        assert not store.completed
    asyncio.run(run())


def test_sse_has_one_final_and_cached_replay():
    store = MemorySessions()
    app.state.chat = ChatService(None, store, SimpleNamespace(graph=FakeGraph()))
    b = body()
    client = TestClient(app)
    first = client.post("/chat", json=b.model_dump(mode="json"))
    assert first.status_code == 200
    assert "text/event-stream" in first.headers["content-type"]
    assert first.text.count("event: final") == 1
    second = client.post("/chat", json=b.model_dump(mode="json"))
    assert second.text.count("event: final") == 1
    assert "event: progress" not in second.text


def test_chat_extra_fields_rejected():
    data = body().model_dump(mode="json") | {"selected_sku": "A"}
    assert TestClient(app).post("/chat", json=data).status_code == 422


def test_cancelled_request_does_not_commit_normal_state():
    async def run():
        store = MemorySessions()
        service = ChatService(None, store, SimpleNamespace(graph=FakeGraph(delay=10)))
        job, _ = await service.submit(body())
        await asyncio.sleep(.01)
        job.task.cancel()
        result = await job.task
        assert result.error["code"] == "REQUEST_CANCELLED"
        assert not store.completed
    asyncio.run(run())


def test_orphaned_inflight_request_not_executed_again():
    async def run():
        store = MemorySessions()
        store.register = lambda b: {"_inflight": True}
        runner = FakeGraph()
        service = ChatService(None, store, SimpleNamespace(graph=runner))
        job, result = await service.submit(body())
        assert job is None
        assert result.error["code"] == "REQUEST_CANCELLED"
        assert not runner.calls
    asyncio.run(run())


