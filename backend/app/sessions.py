"""상담용 DB 접근. 한 프로세스의 FIFO 큐 + DB 버전 검증으로 실행/저장을 분리한다."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import text

from backend.app.tools import BusinessError


def encode(value):
    return json.dumps(jsonable_encoder(value), ensure_ascii=False)


def session_error(row):
    if row is None:
        raise BusinessError("SESSION_NOT_FOUND", "새 상담을 시작해 주세요.", 404)
    if row["expires_at"] <= datetime.now(timezone.utc):
        raise BusinessError("SESSION_EXPIRED", "상담이 만료되었습니다. 새 상담을 시작해 주세요.", 410)


class SessionRepository:
    def __init__(self, engine):
        self.engine = engine

    def initialize(self):
        with self.engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(42786031)"))
            conn.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS assistant")
            conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS assistant.migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
            for file in sorted((Path(__file__).parents[1] / "migrations").glob("*.sql")):
                if not conn.execute(text("SELECT 1 FROM assistant.migrations WHERE name=:name"), {"name": file.name}).first():
                    conn.exec_driver_sql(file.read_text(encoding="utf-8"))
                    conn.execute(text("INSERT INTO assistant.migrations(name) VALUES (:name)"), {"name": file.name})
            # 단일 worker로 운영한다. 재시작 시 진행 중이던 작업은 재개하지 않는다.
            pending = conn.execute(text("SELECT session_id, request_id FROM assistant.requests WHERE status IN ('QUEUED','RUNNING')")).mappings().all()
            for row in pending:
                response = {"request_id": str(row["request_id"]), "session_id": str(row["session_id"]),
                    "status": "ERROR", "message": "이전 요청이 중단되었습니다. 새 요청으로 다시 시도해 주세요.",
                    "data": None, "questions": [], "sources": [], "evidence_status": "NOT_USED", "warnings": [],
                    "error": {"code": "REQUEST_CANCELLED", "retryable": True}}
                conn.execute(text("UPDATE assistant.requests SET status='FAILED', response=CAST(:result AS jsonb) WHERE session_id=:sid AND request_id=:rid"),
                             {"sid": row["session_id"], "rid": row["request_id"], "result": encode(response)})

    def _session(self, conn, session_id, lock=False):
        row = conn.execute(text("SELECT * FROM assistant.sessions WHERE session_id=:sid" +
                                (" FOR UPDATE" if lock else "")), {"sid": session_id}).mappings().first()
        session_error(row)
        return row

    def create(self, conn=None):
        if conn is None:
            with self.engine.begin() as transaction:
                return self.create(transaction)
        return dict(conn.execute(text("INSERT INTO assistant.sessions(session_id, expires_at) VALUES (:sid, now()+interval '30 minutes') RETURNING session_id, expires_at"),
                                 {"sid": uuid4()}).mappings().one())

    def register(self, body):
        digest = hashlib.sha256(body.message.encode()).hexdigest()
        with self.engine.begin() as conn:
            self._session(conn, body.session_id, True)
            old = conn.execute(text("SELECT * FROM assistant.requests WHERE session_id=:sid AND request_id=:rid"),
                               {"sid": body.session_id, "rid": body.request_id}).mappings().first()
            if old:
                if old["input_hash"] != digest:
                    raise BusinessError("REQUEST_CONFLICT", "다른 입력에는 새 요청 ID를 사용해 주세요.", 409)
                return old["response"] if old["response"] is not None else {"_inflight": True}
            conn.execute(text("INSERT INTO assistant.requests(session_id,request_id,input_hash,status) VALUES (:sid,:rid,:hash,'QUEUED')"),
                         {"sid": body.session_id, "rid": body.request_id, "hash": digest})
            conn.execute(text("UPDATE assistant.sessions SET expires_at=now()+interval '30 minutes' WHERE session_id=:sid"), {"sid": body.session_id})
        return None

    def load(self, body):
        with self.engine.begin() as conn:
            row = self._session(conn, body.session_id, True)
            messages = conn.execute(text("SELECT user_message, assistant_message FROM assistant.messages WHERE session_id=:sid ORDER BY message_id DESC LIMIT 5"), {"sid": body.session_id}).mappings().all()
            lists = conn.execute(text("SELECT list_id, items FROM assistant.recommendation_lists WHERE session_id=:sid ORDER BY list_order DESC LIMIT 2"), {"sid": body.session_id}).mappings().all()
            conn.execute(text("UPDATE assistant.requests SET status='RUNNING' WHERE session_id=:sid AND request_id=:rid AND status='QUEUED'"), {"sid": body.session_id, "rid": body.request_id})
            return {"state": row["state"], "version": row["version"], "expires_at": row["expires_at"], "messages": [dict(m) for m in reversed(messages)], "lists": [dict(r) for r in lists]}

    def finish(self, body, version, state, result):
        with self.engine.begin() as conn:
            row = self._session(conn, body.session_id, True)
            if row["version"] != version:
                raise BusinessError("REQUEST_CANCELLED", "상담이 초기화되었습니다. 새 상담에서 요청해 주세요.", 409)
            request = conn.execute(text("SELECT status FROM assistant.requests WHERE session_id=:sid AND request_id=:rid FOR UPDATE"), {"sid": body.session_id, "rid": body.request_id}).scalar_one()
            if request != "RUNNING":
                raise BusinessError("REQUEST_CANCELLED", "요청이 중단되었습니다. 새 요청을 보내주세요.", 409)
            conn.execute(text("UPDATE assistant.sessions SET state=CAST(:state AS jsonb), version=version+1 WHERE session_id=:sid"), {"state": encode(state), "sid": body.session_id})
            conn.execute(text("INSERT INTO assistant.messages(session_id,user_message,assistant_message) VALUES (:sid,:user,:answer)"), {"sid": body.session_id, "user": body.message, "answer": result.message})
            conn.execute(text("DELETE FROM assistant.messages WHERE session_id=:sid AND message_id NOT IN (SELECT message_id FROM assistant.messages WHERE session_id=:sid ORDER BY message_id DESC LIMIT 5)"), {"sid": body.session_id})
            displayed = (result.data or {}).get('recommendations') or (result.data or {}).get('sales_ranking')
            if displayed:
                items = [{k: item[k] for k in ("position", "product_id", "product_name", "representative_variant")} for item in displayed]
                conn.execute(text("INSERT INTO assistant.recommendation_lists(list_id,session_id,items) VALUES (:lid,:sid,CAST(:items AS jsonb))"), {"lid": uuid4(), "sid": body.session_id, "items": encode(items)})
                conn.execute(text("DELETE FROM assistant.recommendation_lists WHERE session_id=:sid AND list_id NOT IN (SELECT list_id FROM assistant.recommendation_lists WHERE session_id=:sid ORDER BY list_order DESC LIMIT 2)"), {"sid": body.session_id})
            conn.execute(text("UPDATE assistant.requests SET status='DONE',response=CAST(:result AS jsonb) WHERE session_id=:sid AND request_id=:rid"), {"sid": body.session_id, "rid": body.request_id, "result": encode(result)})

    def fail(self, body, result):
        with self.engine.begin() as conn:
            conn.execute(text("UPDATE assistant.requests SET status='FAILED',response=CAST(:result AS jsonb) WHERE session_id=:sid AND request_id=:rid AND status IN ('QUEUED','RUNNING')"), {"sid": body.session_id, "rid": body.request_id, "result": encode(result)})

    def reset(self, session_id, request_id):
        with self.engine.begin() as conn:
            old = conn.execute(text("SELECT * FROM assistant.requests WHERE session_id=:sid AND request_id=:rid"), {"sid": session_id, "rid": request_id}).mappings().first()
            if old:
                if old["input_hash"] != "RESET":
                    raise BusinessError("REQUEST_CONFLICT", "새 요청 ID를 사용해 주세요.", 409)
                self._session(conn, old["response"]["session_id"])
                return old["response"]
            self._session(conn, session_id, True)
            session = self.create(conn)
            conn.execute(text("UPDATE assistant.sessions SET expires_at=now(), version=version+1, state='{}'::jsonb WHERE session_id=:sid"), {"sid": session_id})
            conn.execute(text("INSERT INTO assistant.requests(session_id,request_id,input_hash,status,response) VALUES (:sid,:rid,'RESET','DONE',CAST(:result AS jsonb))"), {"sid": session_id, "rid": request_id, "result": encode(session)})
            return session

    def cleanup(self):
        with self.engine.begin() as conn:
            # 접근은 30분에 즉시 차단한다. 만료 원문/목록은 분 단위 정리하고 ID는 하루 유지한다.
            for table in ("messages", "recommendation_lists"):
                conn.execute(text(f"DELETE FROM assistant.{table} WHERE session_id IN (SELECT session_id FROM assistant.sessions WHERE expires_at<=now())"))
            conn.execute(text("UPDATE assistant.sessions SET state='{}'::jsonb WHERE expires_at<=now() AND state<>'{}'::jsonb"))
            conn.execute(text("DELETE FROM assistant.requests WHERE session_id IN (SELECT session_id FROM assistant.sessions WHERE expires_at<=now()) AND input_hash<>'RESET'"))
            conn.execute(text("DELETE FROM assistant.sessions WHERE expires_at < now()-interval '1 day'"))
