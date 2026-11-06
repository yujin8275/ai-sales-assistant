import os
from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.app.models import ChatRequest, Response
from backend.app.repository import make_engine
from backend.app.sessions import SessionRepository
from backend.app.tools import BusinessError

pytestmark = pytest.mark.skipif(os.getenv("RUN_DB_TESTS") != "1", reason="DB 통합 테스트 별도 실행")


@pytest.fixture
def sessions():
    engine = make_engine()
    repo = SessionRepository(engine)
    created = repo.create()
    ids = [created["session_id"]]
    yield repo, created, ids
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM assistant.sessions WHERE session_id=ANY(:ids)"), {"ids": ids})
    engine.dispose()


def request(sid, message="테스트"):
    return ChatRequest(session_id=sid, request_id=uuid4(), message=message)


def complete(repo, b, recommendations=False):
    repo.register(b)
    context = repo.load(b)
    result = Response(request_id=b.request_id, session_id=b.session_id, status="OK", message="완료",
        data={"recommendations": [{"position": 1, "product_id": "RM-15C", "product_name": "폰", "representative_variant": {"sku": "RM-15C-BK-4-128"}}]} if recommendations else None)
    repo.finish(b, context["version"], {"constraints": {"quantity": 3}}, result)
    return result


def test_db_completed_replay_and_input_conflict(sessions):
    repo, session, _ = sessions
    b = request(session["session_id"])
    result = complete(repo, b)
    assert repo.register(b) == result.model_dump(mode="json")
    with pytest.raises(BusinessError) as exc:
        repo.register(b.model_copy(update={"message": "다른 입력"}))
    assert exc.value.code == "REQUEST_CONFLICT"


def test_five_pairs_and_two_lists_retained(sessions):
    repo, session, _ = sessions
    for n in range(7):
        complete(repo, request(session["session_id"], str(n)), recommendations=True)
    b = request(session["session_id"])
    repo.register(b)
    context = repo.load(b)
    assert len(context["messages"]) == 5
    assert context["messages"][0]["user_message"] == "2"
    assert len(context["lists"]) == 2


def test_expiry_blocks_cached_response(sessions):
    repo, session, _ = sessions
    b = request(session["session_id"])
    complete(repo, b)
    with repo.engine.begin() as conn:
        conn.execute(text("UPDATE assistant.sessions SET expires_at=now()-interval '1 second' WHERE session_id=:sid"), {"sid": b.session_id})
    with pytest.raises(BusinessError) as exc:
        repo.register(b)
    assert exc.value.http_status == 410


def test_reset_cancels_old_commit_and_is_repeatable(sessions):
    repo, session, ids = sessions
    b = request(session["session_id"])
    repo.register(b)
    context = repo.load(b)
    reset_id = uuid4()
    new = repo.reset(b.session_id, reset_id)
    ids.append(new["session_id"])
    assert str(repo.reset(b.session_id, reset_id)["session_id"]) == str(new["session_id"])
    with pytest.raises(BusinessError):
        repo.finish(b, context["version"], {}, Response(request_id=b.request_id, status="OK", message="늦은 결과"))
    assert new["session_id"] != b.session_id
