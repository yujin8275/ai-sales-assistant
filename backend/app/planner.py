"""하나의 행동 제안과 서버 검증. 상품 ID는 모델이 만들지 않고 서버에서 해석한다."""
import copy
import logging
import re
from typing import Literal

from pydantic import Field, model_validator
from backend.app.models import InputModel, ChatAction, RecommendFilters, Quantity, Text
from backend.app.interpretation import normalize, mentioned_products, mentioned_positions, budget_in


class Target(InputModel):
    name: Text | None = None
    position: int | None = Field(default=None,ge=1,le=5,strict=True)
    sku: Text | None = None
    quantity: Quantity | None = None
    quantity_evidence: str | None = None

    @model_validator(mode='after')
    def one_reference(self):
        if sum(v is not None for v in (self.name,self.position,self.sku))!=1:
            raise ValueError('대상은 이름·순번·SKU 중 하나로 지정')
        return self


class Decision(InputModel):
    action: Literal['recommend','show_options','explain','quote','compare','sales_rank','update_pending','clarify']
    target: Target | None = None
    targets: list[Target] = Field(default_factory=list)
    values: dict = Field(default_factory=dict)
    evidence: dict[str,str] = Field(default_factory=dict)
    clear_fields: list[str] = Field(default_factory=list)
    scope: Literal['catalog','referenced_list'] = 'catalog'
    scope_reference: str = ''
    field: Literal['quantity','sku','product','intent'] | None = None

    @model_validator(mode='after')
    def check_values(self):
        RecommendFilters.model_validate(self.values)
        if any(k not in RecommendFilters.model_fields or k=='scope_product_ids' for k in self.clear_fields):
            raise ValueError('알 수 없는 조건 해제')
        if 'scope_product_ids' in self.values:
            raise ValueError('검색 범위 ID는 서버만 지정')
        if self.action=='update_pending' and (self.target or self.targets):
            raise ValueError('부분 답변에서 대상 재선택 금지')
        if self.action in ('recommend','sales_rank') and (self.target or self.targets):
            # 추천/판매 순위는 개별 상품 선택을 변경하지 않는다.
            self.target=None
            self.targets=[]
        return self


ACTION_INTENT={'recommend':'RECOMMEND','show_options':'DETAILS','explain':'KNOWLEDGE',
               'quote':'QUOTE','compare':'COMPARE','sales_rank':'RANKING'}


def active_task(state):
    if state.get('task'):return state['task']
    waiting=[]
    for question in state.get('pending_question',[]):waiting.extend(question.get('missing_fields',[]))
    return {'intent':state.get('pending_intent') or state.get('last_intent'),'waiting_for':list(dict.fromkeys(waiting))}


def quantity_value(message):
    """의도 분류가 아닌, 수량 슬롯의 단위/표기 정규화."""
    compact=re.sub(r'\s+','',message).strip('.!?~')
    compact=re.sub(r'^(?:구매)?수량(?:은|을)?','',compact)
    compact=re.sub(r'(?:로)?(?:변경해주세요|변경해줘|해주세요|해줘|부탁해요|부탁해|주세요|요)$','',compact)
    compact=compact.removesuffix('로')
    if re.fullmatch(r'\d+(?:대|개)?',compact):return int(re.match(r'\d+',compact)[0])
    numbers={'한':1,'하나':1,'두':2,'둘':2,'세':3,'셋':3,'네':4,'넷':4,'다섯':5,'여섯':6,'일곱':7,'여덟':8,'아홉':9,'열':10}
    for word,value in numbers.items():
        if word=='네' and compact=='네':continue
        if compact in (word,word+'개',word+'대'):return value
    return None


def pending_answer(message,state):
    task=active_task(state)
    quantity_context=task.get('intent')=='QUOTE' and ('quantity' in task.get('waiting_for',[]) or state.get('selected_items'))
    if not quantity_context:return None
    if message.strip() in ('네','예','맞아','맞아요','응'):
        if state.get('quantity_confirmation') is not None:
            return Decision(action='update_pending',values={'quantity':state['quantity_confirmation']})
        return Decision(action='clarify',field='quantity')
    value=quantity_value(message)
    if value is not None:
        if not 1<=value<=2147483647:return Decision(action='clarify',field='quantity')
        return Decision(action='update_pending',values={'quantity':value})
    if re.fullmatch(r'\s*\d+\s*[A-Za-z]+\s*',message):
        return Decision(action='clarify',field='quantity')
    return None


class PlanningIssue(Exception):
    def __init__(self,message,field='product',hint=None):
        self.message,self.field,self.hint=message,field,hint


def require_literal(value,message):
    return bool(re.search(r'(?<![A-Za-z0-9_-])'+re.escape(value)+r'(?![A-Za-z0-9_-])',message,re.I))


def resolve(decision,context,message,catalogue,variants):
    """검증이 모두 끝난 뒤 상태 사본에 한 번만 적용한다. 실패 시 원본은 그대로 둔다."""
    state=copy.deepcopy(context['state'])
    state.setdefault('constraints',{}).pop('scope_product_ids',None)
    provided_values=bool(decision.values)
    # 모델이 확정값을 반복해도 새 변경으로 해석하지 않는다.
    decision=decision.model_copy(update={'values':{k:v for k,v in decision.values.items()
        if state['constraints'].get(k)!=v}})
    task=active_task(state)
    if decision.action=='update_pending' and not task.get('waiting_for') and task.get('intent') in ('RECOMMEND','RANKING'):
        decision=decision.model_copy(update={'action':'recommend' if task['intent']=='RECOMMEND' else 'sales_rank'})
    if decision.action=='clarify':
        if decision.field=='quantity':
            match=re.fullmatch(r'\s*(\d+)\s*[A-Za-z]+\s*',message)
            if match and 1<=int(match[1])<=2147483647:
                raise PlanningIssue(f"{int(match[1])}개를 말씀하신 건가요?",'quantity',int(match[1]))
            raise PlanningIssue('구매 수량을 알려주세요. 예: 2개, 두 개, 2대.','quantity')
        raise PlanningIssue('원하시는 작업이나 상품을 조금 더 구체적으로 알려주세요.',decision.field or 'intent')
    if decision.action=='update_pending':
        if not task.get('intent'):
            raise PlanningIssue('어떤 상품이나 요청의 조건을 변경할지 알려주세요.','intent')
        allowed=set(RecommendFilters.model_fields)-{'scope_product_ids'}
        if task['intent']=='QUOTE' and task.get('waiting_for')==['quantity']:
            allowed={'quantity','card_company'}
        if not decision.values and not decision.clear_fields and not provided_values:
            raise PlanningIssue('답변을 명확히 이해하지 못했습니다. 필요한 항목만 다시 알려주세요.','quantity' if task.get('waiting_for')==['quantity'] else 'intent')
        if not (set(decision.values)|set(decision.clear_fields))<=allowed:
            raise PlanningIssue('선택한 상품은 유지하고 구매 수량을 알려주세요.','quantity')
        intent=task['intent']
    else:intent=ACTION_INTENT[decision.action]
    targets=[]
    skus=[]
    selected=[]
    refs=decision.targets or ([decision.target] if decision.target else [])
    for ref in refs:
        exact_sku=ref.sku or (ref.name if any(r['sku']==ref.name for r in variants) else None)
        if ref.position is not None:
            if ref.position not in mentioned_positions(message):raise PlanningIssue('선택할 상품의 순번이나 이름을 알려주세요.')
            listing=context.get('lists',[])
            if not listing:raise PlanningIssue('현재 추천 목록이 없습니다. 상품명을 알려주세요.')
            if '아까' in message and len(listing)>1:raise PlanningIssue('현재 목록과 이전 목록 중 어느 상품인지 상품명으로 알려주세요.')
            item=next((p for p in listing[0]['items'] if p['position']==ref.position),None)
            if not item:raise PlanningIssue('현재 목록에 없는 순번입니다. 상품명을 알려주세요.')
            targets.append(item['product_id'])
        elif exact_sku:
            if not require_literal(exact_sku,message):raise PlanningIssue('구매할 SKU를 직접 선택해 주세요.','sku')
            row=next((r for r in variants if r['sku']==exact_sku),None)
            if row is None:raise PlanningIssue('등록된 SKU를 확인해 다시 선택해 주세요.','sku')
            skus.append(exact_sku);targets.append(row['product_id'])
            item={'sku':exact_sku}
            if ref.quantity is not None:
                if (not ref.quantity_evidence or not require_literal(ref.quantity_evidence,message)
                        or quantity_value(ref.quantity_evidence)!=ref.quantity):
                    raise PlanningIssue('SKU별 구매 수량을 확인해 주세요.','quantity')
                item['quantity']=ref.quantity
            selected.append(item)
        else:
            if not normalize(ref.name) or normalize(ref.name) not in normalize(message):
                raise PlanningIssue('어느 상품을 말씀하시는지 상품명을 알려주세요.')
            found=mentioned_products(ref.name,catalogue)
            if len(found)!=1:raise PlanningIssue('해당 이름의 상품을 하나로 확인할 수 없습니다. 정확한 상품명을 알려주세요.')
            targets.extend(found)
    if decision.action=='quote' and not refs and not state.get('selected_items') and not state.get('selected_product_ids'):
        raise PlanningIssue('견적을 받을 상품이나 SKU를 알려주세요.')
    if decision.action!='update_pending':
        for key in list(decision.values)+decision.clear_fields:
            evidence=decision.evidence.get(key,'').strip()
            if not evidence or evidence not in message:
                raise PlanningIssue('변경할 조건을 명확히 확인하지 못했습니다. 조건을 다시 알려주세요.','quantity' if key=='quantity' else 'intent')
    if 'quantity' in decision.values:
        evidence=decision.evidence.get('quantity','')
        value=quantity_value(evidence)
        if decision.action!='update_pending' and (value!=decision.values['quantity'] or not require_literal(evidence,message)):
            raise PlanningIssue('구매 수량을 다시 확인해 주세요.','quantity')
    if 'budget' in decision.values and decision.action!='update_pending':
        amount=budget_in(decision.evidence.get('budget',''))
        if amount is not None and decision.values['budget'].get('comparison')!='RANGE' and amount!=decision.values['budget']['amount']:
            raise PlanningIssue('예산 금액을 다시 확인해 주세요.','intent')
    filters=copy.deepcopy(state.get('constraints',{}))
    for key in decision.clear_fields:filters.pop(key,None)
    filters.update(decision.values)
    if 'storage_gb' in decision.values:filters.pop('min_storage_gb',None)
    if 'min_storage_gb' in decision.values:filters.pop('storage_gb',None)
    RecommendFilters.model_validate(filters)
    if targets and list(dict.fromkeys(targets))!=state.get('selected_product_ids'):
        state.pop('selected_items',None)
    if targets:state['selected_product_ids']=list(dict.fromkeys(targets))
    if skus:state['selected_items']=selected
    elif set(decision.values)&{'colors','storage_gb','ram_gb'}:state.pop('selected_items',None)
    if 'quantity' in decision.values and state.get('selected_items'):
        if len(state['selected_items'])>1 and not skus:
            raise PlanningIssue('어느 SKU의 수량을 변경할지 알려주세요.','sku')
        for item in state['selected_items']:item['quantity']=decision.values['quantity']
    state['constraints']=filters
    for key in decision.clear_fields:state.setdefault('preferences',{})[key]='ANY'
    state.pop('quantity_confirmation',None)
    state['planner_version']=2
    search_ids=None
    reference=decision.scope_reference.strip()
    explicit_reference=bool(reference and reference in message and re.search(r'그\s*중|이\s*중|목록|추천.*중',reference))
    # 목록 한정은 현재 발화 근거가 있는 경우만 부여한다. 모델이 과거
    # 참조를 반복해도 기본 전체 검색을 바꾸거나 불필요한 되질문을 하지 않는다.
    if intent in ('RECOMMEND','RANKING') and decision.scope=='referenced_list' and explicit_reference:
        if '아까' in reference and len(context.get('lists',[]))>1:
            raise PlanningIssue('현재 목록과 이전 목록 중 어느 목록인지 알려주세요.','intent')
        if not context.get('lists'):raise PlanningIssue('참조할 추천 목록이 없습니다. 전체 상품에서 찾아드릴까요?','intent')
        search_ids=[p['product_id'] for p in context['lists'][0]['items']]
    action=ChatAction(intent=intent,within_latest=search_ids is not None,search_product_ids=search_ids)
    logging.getLogger('uvicorn.error').info('planner_action=%s intent=%s target_count=%d changed_fields=%s',
        decision.action,intent,len(targets),','.join(decision.values))
    return state,action
