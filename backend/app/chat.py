import asyncio
import copy
import re
import logging
import time
from dataclasses import dataclass, field
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import StateGraph, START, END
from sqlalchemy.exc import SQLAlchemyError

from backend.app.chat_model import ChatModel
from backend.app.models import ChatAction, ProductFilters, QuoteItem, RecommendFilters, RecommendRequest, Response
from backend.app.recommendation import recommend
from backend.app.repository import read_once_retry
from backend.app.tools import BusinessError, ProductTool, QuoteTool
from backend.app.knowledge import answer_product_question
from backend.app.interpretation import mentioned_positions


def error_response(body, code, message, retryable=True):
    return Response(request_id=body.request_id, session_id=body.session_id, status="ERROR",
                    message=message, error={"code": code, "retryable": retryable})


def need_input(body, text, fields, data=None, options=None):
    return Response(request_id=body.request_id, session_id=body.session_id, status="NEED_INPUT",
        message=text, data=data, questions=[{"question_id": "clarify", "text": text,
        "missing_fields": fields, "options": options or [], "allow_free_text": True}])


def resolve_targets(action, context, message):
    lists = context["lists"]
    if (action.ambiguous_reference or "아까" in message) and len(lists) > 1:
        return None
    positions = mentioned_positions(message) or action.positions
    if positions:
        latest = lists[0]["items"] if lists else []
        targets = [next((i["product_id"] for i in latest if i["position"] == n), None) for n in positions]
        return targets if all(targets) else None
    return action.product_ids


class GraphState(TypedDict, total=False):
    body: object
    context: dict
    state: dict
    action: ChatAction
    result: Response
    emit: object
    blocked: bool


class ChatFlow:
    def __init__(self, engine, model=None):
        self.engine, self.model = engine, model or ChatModel()
        graph = StateGraph(GraphState)
        graph.add_node("analyze", self.analyze)
        graph.add_node("execute", self.execute)
        graph.add_node("finalize", self.finalize)
        graph.add_edge(START, "analyze")
        graph.add_edge("analyze", "execute")
        graph.add_edge("execute", "finalize")
        graph.add_edge("finalize", END)
        self.graph = graph.compile()

    async def analyze(self, graph):
        from backend.app.planner import pending_answer, resolve, PlanningIssue, active_task, ACTION_INTENT
        graph['emit']('ANALYZING','현재 상담과 요청을 확인하고 있습니다.')
        context=graph['context']
        state=copy.deepcopy(context['state'])
        state.setdefault('constraints',{}).pop('scope_product_ids',None)
        context={**context,'state':state}
        decision=pending_answer(graph['body'].message,state)
        if decision is None:
            decision=await self.model.plan(graph['body'].message,context)
        refs=decision.targets or ([decision.target] if decision.target else [])
        def lookup(repo):
            catalogue=repo.catalogue() if any(r.name for r in refs) else []
            # 모델이 판매 식별자를 name 필드에 담아도 DB의 정확한 SKU로 확인한다.
            skus=[r.sku or r.name for r in refs if r.sku or r.name]
            return catalogue,repo.variants(skus) if skus else []
        catalogue,variants=await asyncio.to_thread(read_once_retry,self.engine,lookup)
        try:
            state,action=resolve(decision,context,graph['body'].message,catalogue,variants)
            return {'state':state,'action':action,'blocked':False}
        except PlanningIssue as issue:
            if issue.hint is not None:state['quantity_confirmation']=issue.hint
            intent=ACTION_INTENT.get(decision.action) or active_task(state).get('intent') or 'UNKNOWN'
            state['task']={'intent':intent,'waiting_for':[issue.field]}
            return {'state':state,'action':ChatAction(intent='UNKNOWN'),'blocked':True,
                'result':need_input(graph['body'],issue.message,[issue.field])}

    async def execute(self, graph):
        if graph.get('blocked'):return {'state':graph['state'],'result':graph['result']}
        body,state,action=graph['body'],graph['state'],graph['action']
        emit=graph['emit']
        emit('CHECKING_INPUT','대상과 구매 조건을 확인하고 있습니다.')
        intent=action.intent
        execution_filters=copy.deepcopy(state.get('constraints',{}))
        if action.search_product_ids is not None:execution_filters['scope_product_ids']=action.search_product_ids
        validated=RecommendFilters.model_validate(execution_filters)
        if intent=='RECOMMEND':
            emit('SEARCHING_PRODUCTS','조건에 맞는 상품을 확인하고 있습니다.')
            if validated.purpose:emit('SEARCHING_DOCUMENTS','설명서 근거와 용도 적합성을 확인하고 있습니다.')
            limit=3 if action.within_latest and validated.purpose else 5
            result=await recommend(self.engine,RecommendRequest(request_id=body.request_id,filters=validated,limit=limit),self.model)
            result.session_id=body.session_id
            if action.within_latest:result.message='직전 추천 목록 안에서 다시 비교했습니다. '+result.message
            if result.status=='OK':
                state['phase']='RECOMMENDED'
                state.pop('selected_items',None)
                state.pop('selected_product_ids',None)
            if validated.budget:result.warnings.append('예산은 '+('1대 기준입니다.' if validated.budget.scope=='PER_UNIT' else '전체 수량의 총액 기준입니다.'))
        elif intent=='QUOTE':
            emit('CALCULATING_QUOTE','선택한 옵션과 수량으로 견적을 확인하고 있습니다.')
            result=await self.quote(body,state,validated)
        elif intent=='KNOWLEDGE':
            ids=state.get('selected_product_ids',[])
            if len(ids)!=1:result=need_input(body,'설명할 상품 한 개를 알려주세요.',['product'])
            else:
                emit('SEARCHING_DOCUMENTS','해당 제품의 설명서에서 근거를 찾고 있습니다.')
                result=await answer_product_question(self.engine,self.model,body,ids[0])
        elif intent in ('DETAILS','STOCK','COMPARE','RANKING'):
            emit('SEARCHING_PRODUCTS','상품 정보를 확인하고 있습니다.')
            result=await self.product_request(body,state,validated,intent,[])
        else:result=need_input(body,'추천·제품 설명·비교·견적 중 원하시는 작업을 알려주세요.',['intent'])
        waiting=[field for q in result.questions for field in q.get('missing_fields',[])]
        state['task']={'intent':intent,'waiting_for':list(dict.fromkeys(waiting))}
        state['last_intent']=intent
        if result.questions:
            state['pending_intent']=intent
            state['pending_question']=result.questions
        else:
            state.pop('pending_intent',None)
            state.pop('pending_question',None)
        return {'state':state,'result':result}

    async def quote(self, body, state, filters):
        items = state.get("selected_items", [])
        products = state.get("selected_product_ids", [])
        quantity = state["constraints"].get("quantity")
        if items:
            if quantity is not None:
                items = [i if "quantity" in i else i | {"quantity": quantity} for i in items]
            if any("quantity" not in i for i in items):
                return need_input(body, "구매 수량을 알려주세요.", ["quantity"])
        elif products:
            results = await asyncio.to_thread(read_once_retry, self.engine, lambda repo: [
                ProductTool(repo).get_product_details(pid, storage_gb=filters.storage_gb,
                    ram_gb=filters.ram_gb, requested_quantity=quantity) for pid in products])
            if any(r.status == "NOT_FOUND" for r in results):
                return Response(request_id=body.request_id, session_id=body.session_id, status="NOT_FOUND", message="등록된 상품을 확인할 수 없습니다.")
            items, variants = [], []
            for result in results:
                options = result.data["variants"]
                if filters.colors:
                    options = [v for v in options if v["color"] in filters.colors]
                variants.extend(options)
                if len(options) == 1:
                    items.append({"sku": options[0]["sku"], **({"quantity": quantity} if quantity else {})})
            if len(items) != len(products):
                data={"variants": variants}
                if len(results)>1:
                    data['products']=[r.data['product'] for r in results]
                name=''
                if len(results)==1:
                    data['product']=results[0].data['product']
                    name=data['product'].get('product_name','')
                message=(f"{name} {quantity}대 견적을 위해 " if name and quantity else f"{name}: " if name else '')
                return need_input(body, message+"구매할 옵션의 SKU를 선택해 주세요." + (" 수량도 알려주세요." if quantity is None else ""),
                    ["sku", "quantity"] if quantity is None else ["sku"], data=data,
                    options=[{"label": f"{v['color']} · RAM {v['ram_gb']}GB · {v['storage_gb']}GB · {v['sale_price']:,}원 · 재고 {v['stock_quantity']}대",
                              "message": v["sku"] + (f"로 {quantity}대 견적 내줘" if quantity else "로 견적 내줘")} for v in variants])
            state["selected_items"] = items
            if quantity is None:
                return need_input(body, "구매 수량을 알려주세요.", ["quantity"])
        else:
            return need_input(body, "견적을 받을 상품과 구매 수량을 알려주세요.", ["product_id", "quantity"])
        typed = [QuoteItem.model_validate(i) for i in items]
        tool = await asyncio.to_thread(read_once_retry, self.engine, lambda repo:
            QuoteTool(repo).calculate_quote(typed, filters.card_company))
        state["selected_items"] = [i.model_dump() for i in typed]
        if tool.status == "OK":
            state["last_quote"] = tool.data["quote"]
            state["phase"] = "QUOTED"
            quote = tool.data["quote"]
            message = f"총 견적은 {quote['total']:,}원입니다."
            warnings = [] if filters.card_company else ["판매가 기준입니다. 카드사를 알려주시면 할인을 확인할 수 있습니다."]
        else:
            message = "미등록 SKU 또는 부족 품목을 확인해 주세요. 전체 견적은 완료하지 않았습니다."
            warnings = []
        questions = []
        if tool.status == 'OUT_OF_STOCK' and len(typed) == 1:
            issue = tool.data['stock_issues'][0]
            available = issue['available_quantity']
            message = f"요청하신 {issue['requested_quantity']}대 중 {issue['shortage_quantity']}대가 부족합니다. 현재 재고는 {available}대이며, 견적은 완료하지 않았습니다."
            if available:
                questions = [{"question_id": "stock-choice", "text": "구매 가능한 수량으로 변경할까요?",
                    "missing_fields": ["quantity"], "allow_free_text": True,
                    "options": [{"label": f"{available}대로 변경해 재계산", "message": f"{issue['sku']}로 {available}대 견적 내줘"}]}]
        return Response(request_id=body.request_id, session_id=body.session_id, status=tool.status,
                        message=message, data=tool.data, warnings=warnings, questions=questions)

    async def product_request(self, body, state, filters, intent, criteria):
        ids = state.get("selected_product_ids", [])
        if intent != "RANKING" and (not ids or intent == "COMPARE" and len(ids) < 2):
            return need_input(body, "확인할 상품을 알려주세요." if intent != "COMPARE" else "비교할 상품 두 개를 알려주세요.", ["product_id"])
        def run(repo):
            tool = ProductTool(repo)
            if intent == "RANKING":
                product_filters = ProductFilters.model_validate(filters.model_dump(exclude_none=True,
                    exclude={"budget", "purpose", "card_company"}))
                return tool.get_sales_ranking(product_filters)
            if intent == "COMPARE":
                return tool.compare_products(ids, criteria or ["battery_mah", "weight_g", "display_inches"])
            return tool.get_product_details(ids[0], storage_gb=filters.storage_gb,
                ram_gb=filters.ram_gb, requested_quantity=state["constraints"].get("quantity"))
        result = await asyncio.to_thread(read_once_retry, self.engine, run)
        message = "등록된 상품 정보입니다." if result.status == "OK" else "등록된 상품을 찾지 못했습니다."
        if intent == 'RANKING' and result.data is not None:
            ranking = result.data.get('sales_ranking', [])
            message = (f"최근 3개월 판매량 기준 상위 {len(ranking)}기종입니다. SKU별 판매량을 기종 단위로 합산했으며, {ranking[0]['sales_reference_date']} 집계 기준입니다."
                       if ranking else '현재 조건에서 판매 순위를 확인할 수 있는 상품이 없습니다.')
        if result.status == 'OK' and result.data and result.data.get('variants'):
            colors = list(dict.fromkeys(v['color'] for v in result.data['variants'] if v['color']))
            name = result.data['product']['product_name']
            if re.search(r'색상|컬러|색.*있', body.message):
                message = name + '의 등록 색상은 ' + ', '.join(colors) + '입니다. 옵션별 가격과 재고는 아래에서 확인해 주세요.'
            else:
                message = name + '의 판매 옵션과 재고입니다.'
        return Response(request_id=body.request_id, session_id=body.session_id, status=result.status,
            message=message, data=result.data)

    async def finalize(self, graph):
        graph["emit"]("GENERATING_RESPONSE", "결과 안내를 준비하고 있습니다.")
        result = graph["result"]
        result.data = (result.data or {}) | {"consultation": {
            "constraints": graph["state"].get("constraints", {}),
            "selected_items": graph["state"].get("selected_items", []),
            "expires_at": graph["context"].get("expires_at")}}
        graph["emit"]("VALIDATING_RESPONSE", "결과를 확인하고 있습니다.")
        return {"result": result}


@dataclass
class Job:
    task: object = None
    queues: set = field(default_factory=set)
    watchers: int = 0

    def emit(self, stage, message):
        for queue in self.queues:
            queue.put_nowait({"stage": stage, "message": message})


class ChatService:
    """단일 Uvicorn worker용 FIFO. DB 연결은 모델 대기 중 보유하지 않는다."""
    def __init__(self, engine, sessions, flow=None, timeout=120):
        self.sessions = sessions
        self.flow = flow or ChatFlow(engine)
        self.jobs, self.locks, self.counts = {}, {}, {}
        self.submission = asyncio.Lock()
        self.timeout = timeout

    async def submit(self, body):
        async with self.submission:
            cached = await asyncio.to_thread(self.sessions.register, body)
            key = (body.session_id, body.request_id)
            if cached is not None and cached.get("_inflight") and key not in self.jobs:
                result = error_response(body, "REQUEST_CANCELLED", "이전 요청이 중단되었습니다. 새 요청으로 다시 시도해 주세요.")
                await asyncio.to_thread(self.sessions.fail, body, result)
                return None, result
            if cached is not None and not cached.get("_inflight"):
                return None, Response.model_validate(cached)
            job = self.jobs.get(key)
            if job is None:
                job = Job()
                self.jobs[key] = job
                job.task = asyncio.create_task(self.run(body, job))
                job.task.add_done_callback(lambda task: self.jobs.pop(key, None))
            job.watchers += 1
            return job, None

    async def run(self, body, job):
        started = time.monotonic()
        sid = body.session_id
        lock = self.locks.setdefault(sid, asyncio.Lock())
        self.counts[sid] = self.counts.get(sid, 0) + 1
        async def process():
            async with lock:
                context = await asyncio.to_thread(self.sessions.load, body)
                graph = await self.flow.graph.ainvoke({"body": body, "context": context, "emit": job.emit})
                await asyncio.to_thread(self.sessions.finish, body, context["version"], graph["state"], graph["result"])
                return graph["result"]
        try:
            result = await asyncio.wait_for(process(), self.timeout)
            return result
        except BusinessError as exc:
            result = error_response(body, exc.code, exc.message, exc.http_status >= 500)
        except TimeoutError:
            result = error_response(body, "REQUEST_TIMEOUT", "응답 대기 시간 120초를 초과했습니다. 입력한 내용을 다시 보내주세요.")
        except asyncio.CancelledError:
            result = error_response(body, "REQUEST_CANCELLED", "연결이 종료되어 요청이 중단되었습니다. 새 요청을 보내주세요.")
        except SQLAlchemyError:
            result = error_response(body, "DEPENDENCY_UNAVAILABLE", "상담 정보를 처리할 수 없습니다. 다시 요청해 주세요.")
        except Exception:
            result = error_response(body, "INTERNAL_ERROR", "일시적인 오류입니다. 새 요청으로 다시 시도해 주세요.")
        finally:
            logging.getLogger("uvicorn.error").info("request_id=%s tool=chat status=%s elapsed_ms=%d error_code=%s",
                body.request_id, result.status, int((time.monotonic()-started)*1000),
                (result.error or {}).get("code"))
            self.counts[sid] -= 1
            if not self.counts[sid]:
                self.counts.pop(sid)
                self.locks.pop(sid, None)
        try:
            await asyncio.shield(asyncio.to_thread(self.sessions.fail, body, result))
        except Exception:
            pass
        return result



