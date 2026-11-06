"""1차 구현: LLM 없이 실행되는 직접 견적 API. 세션/채팅/추천은 후속 구현."""
import asyncio
import json
from contextlib import suppress
import logging
import os
import time
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from backend.app.models import QuoteRequest, RecommendRequest, Response, SessionCreate, ResetRequest, ChatRequest, ProductFilters
from backend.app.sessions import SessionRepository
from backend.app.chat import ChatService
from backend.app.recommendation import recommend
from backend.app.repository import make_engine, read_once_retry
from backend.app.tools import BusinessError, QuoteTool, ProductTool

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app):
    app.state.engine = make_engine()
    app.state.sessions = SessionRepository(app.state.engine)
    await asyncio.to_thread(app.state.sessions.initialize)
    app.state.chat = ChatService(app.state.engine, app.state.sessions)
    async def cleanup():
        while True:
            await asyncio.sleep(60)
            try:
                await asyncio.to_thread(app.state.sessions.cleanup)
            except SQLAlchemyError:
                logger.warning("session_cleanup status=ERROR")
    cleaner = asyncio.create_task(cleanup())
    try:
        yield
    finally:
        cleaner.cancel()
        with suppress(asyncio.CancelledError):
            await cleaner
        tasks = [job.task for job in list(app.state.chat.jobs.values())]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        app.state.engine.dispose()


app = FastAPI(title="ABC Electronics API", version="0.3.0", lifespan=lifespan)
app.mount("/images", StaticFiles(directory=os.getenv("PRODUCT_IMAGES_DIR", "/app/product_images"), check_dir=False), name="images")


@app.get('/home', response_model=Response)
async def home(request: Request):
    def load(repo):
        brands = {p['brand'] for p in repo.catalogue()}
        leaders = []
        for brand in ('Xiaomi', 'Samsung', 'Apple'):
            if brand in brands:
                ranking = ProductTool(repo).get_sales_ranking(ProductFilters(brands=[brand]), limit=1)
                leaders.extend(ranking.data['sales_ranking'])
        return {'brand_leaders':leaders, 'featured_products':ProductTool(repo).home_ranking().data['sales_ranking']}
    data = await asyncio.wait_for(asyncio.to_thread(read_once_retry, request.app.state.engine, load), 30)
    return Response(request_id=uuid4(), status='OK', message='최근 3개월 판매 데이터 기준 상품입니다.', data=data)


def failure(request_id, code, message, status, retryable=False, data=None):
    response = Response(request_id=request_id, status="ERROR", message=message,
                        data=data, error={"code": code, "retryable": retryable})
    return JSONResponse(status_code=status, content=jsonable_encoder(response))


@app.exception_handler(RequestValidationError)
async def invalid_input(request, exc):
    request_id = uuid4()
    if isinstance(exc.body, dict):
        try:
            request_id = UUID(str(exc.body.get("request_id")))
        except (ValueError, TypeError):
            pass
    # 입력 원문과 내부 검증 오류는 공개하거나 로그에 남기지 않는다.
    return failure(request_id, "INVALID_INPUT", "입력 항목과 형식을 확인해 주세요.", 422)


@app.exception_handler(BusinessError)
async def business_error(request, exc):
    return failure(getattr(request.state, "request_id", uuid4()), exc.code, exc.message,
                   exc.http_status, exc.http_status >= 500)


@app.exception_handler(SQLAlchemyError)
async def dependency_error(request, exc):
    return failure(getattr(request.state, "request_id", uuid4()), "DEPENDENCY_UNAVAILABLE",
                   "상담 정보를 처리할 수 없습니다. 다시 요청해 주세요.", 503, True)


@app.post("/sessions", status_code=201, response_model=Response)
async def create_session(body: SessionCreate, request: Request):
    session = await asyncio.to_thread(request.app.state.sessions.create)
    return Response(request_id=uuid4(), session_id=session["session_id"], status="OK",
                    message="새 상담을 시작합니다.", data={"session": session})


@app.post("/sessions/{session_id}/reset", response_model=Response)
async def reset_session(session_id: UUID, body: ResetRequest, request: Request):
    request.state.request_id = body.request_id
    session = await asyncio.to_thread(request.app.state.sessions.reset, session_id, body.request_id)
    return Response(request_id=body.request_id, session_id=session["session_id"], status="OK",
                    message="새 상담으로 초기화했습니다.", data={"session": session})


def sse(event, data):
    return "event: " + event + "\ndata: " + json.dumps(jsonable_encoder(data), ensure_ascii=False) + "\n\n"


@app.post("/chat", summary="상담 메시지 전송", description="먼저 POST /sessions로 받은 session_id를 입력하세요. 새 메시지마다 새 request_id(UUID)를 사용합니다. 응답은 진행 상태와 최종 결과를 담은 SSE입니다.", responses={200: {"content": {"text/event-stream": {}}}})
async def chat(body: ChatRequest, request: Request):
    request.state.request_id = body.request_id
    service = request.app.state.chat
    job, cached = await service.submit(body)
    async def events():
        if cached is not None:
            yield sse("error" if cached.status == "ERROR" else "final", cached)
            return
        queue = asyncio.Queue()
        job.queues.add(queue)
        try:
            yield sse("progress", {"request_id": body.request_id, "stage": "QUEUED", "message": "요청을 접수했습니다."})
            while not job.task.done():
                try:
                    progress = await asyncio.wait_for(queue.get(), 2)
                    yield sse("progress", {"request_id": body.request_id, **progress})
                except TimeoutError:
                    yield ": waiting\n\n"
            result = job.task.result()
            yield sse("error" if result.status == "ERROR" else "final", result)
        finally:
            job.queues.discard(queue)
            job.watchers -= 1
            if not job.watchers and not job.task.done():
                job.task.cancel()
                with suppress(asyncio.CancelledError):
                    await job.task
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/quote", response_model=Response)
async def quote(body: QuoteRequest, request: Request):
    started = time.monotonic()
    status = "ERROR"
    error_code = None
    try:
        result = await asyncio.wait_for(asyncio.to_thread(
            read_once_retry, request.app.state.engine,
            lambda repo: QuoteTool(repo).calculate_quote(body.items, body.card_company)), 120)
        status = result.status
        message = {"OK": "견적을 계산했습니다.",
                   "NOT_FOUND": "등록되지 않은 SKU를 확인해 주세요.",
                   "OUT_OF_STOCK": "재고가 부족하여 견적을 완료하지 않았습니다. 수량이나 상품을 변경해 주세요."}[status]
        warnings = []
        if status == "OK" and body.card_company is None:
            warnings.append("판매가 기준 견적입니다. 카드사를 알려주시면 할인 적용 여부를 확인할 수 있습니다.")
        return Response(request_id=body.request_id, status=status, message=message,
                        data=result.data, warnings=warnings)
    except BusinessError as exc:
        error_code = exc.code
        return failure(body.request_id, exc.code, exc.message, exc.http_status)
    except TimeoutError:
        error_code = "REQUEST_TIMEOUT"
        return failure(body.request_id, error_code, "응답 대기 시간 120초를 초과했습니다. 다시 요청해 주세요.", 504, True)
    except SQLAlchemyError:
        error_code = "DEPENDENCY_UNAVAILABLE"
        return failure(body.request_id, error_code, "상품 정보를 조회할 수 없습니다. 잠시 후 다시 요청해 주세요.", 503, True)
    except Exception:
        error_code = "INTERNAL_ERROR"
        return failure(body.request_id, error_code, "일시적인 오류입니다. 다시 요청해 주세요.", 500, True)
    finally:
        logger.info("request_id=%s tool=quote status=%s elapsed_ms=%d error_code=%s",
                       body.request_id, status, int((time.monotonic() - started) * 1000), error_code)


@app.get("/health", response_model=Response)
async def health(request: Request):
    database, model = False, False
    try:
        await asyncio.wait_for(asyncio.to_thread(read_once_retry, request.app.state.engine,
                              lambda repo: repo.check_database()), 10)
        database = True
    except Exception:
        pass
    # 모델명이 설정되고 Ollama에 설치돼 있을 때만 준비된 것으로 표시한다.
    model_name = os.getenv("CHAT_MODEL", "qwen3:8b")
    if model_name:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(os.getenv("OLLAMA_URL", "http://host.docker.internal:11434") + "/api/tags")
                response.raise_for_status()
                model = any(m["name"] == model_name for m in response.json()["models"])
        except Exception:
            pass
    ready = database and model
    data = {"health": {"ready": ready, "dependencies": {"database": database, "model": model}}}
    if not ready:
        return failure(uuid4(), "DEPENDENCY_UNAVAILABLE", "필수 연결이 아직 준비되지 않았습니다.", 503, True, data)
    return Response(request_id=uuid4(), status="OK", message="준비되었습니다.", data=data)


@app.post("/recommend", response_model=Response)
async def recommend_endpoint(body: RecommendRequest, request: Request):
    started = time.monotonic()
    status, code = "ERROR", None
    try:
        result = await asyncio.wait_for(recommend(request.app.state.engine, body), 120)
        status = result.status
        return result
    except BusinessError as exc:
        code = exc.code
        return failure(body.request_id, code, exc.message, exc.http_status,
                       code in ("MODEL_ERROR", "DEPENDENCY_UNAVAILABLE"))
    except TimeoutError:
        code = "REQUEST_TIMEOUT"
        return failure(body.request_id, code, "응답 대기 시간 120초를 초과했습니다. 다시 요청해 주세요.", 504, True)
    except SQLAlchemyError:
        code = "DEPENDENCY_UNAVAILABLE"
        return failure(body.request_id, code, "상품 정보를 조회할 수 없습니다. 잠시 후 다시 요청해 주세요.", 503, True)
    except Exception:
        code = "INTERNAL_ERROR"
        return failure(body.request_id, code, "일시적인 오류입니다. 다시 요청해 주세요.", 500, True)
    finally:
        logger.info("request_id=%s tool=recommend status=%s elapsed_ms=%d error_code=%s",
                    body.request_id, status, int((time.monotonic() - started) * 1000), code)


