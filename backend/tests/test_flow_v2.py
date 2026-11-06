import asyncio,copy
from types import SimpleNamespace
import pytest

from backend.app.chat import ChatFlow
from backend.app.models import ChatRequest,Response
from backend.app.planner import Decision,Target
from backend.tests.test_chat import body
from backend.tests.test_quote import variant


class Repo:
    def catalogue(self):return [{'product_id':'N15','product_name':'Redmi Note 15 5G'},
                               {'product_id':'C15','product_name':'Redmi 15C 5G'}]
    def variants(self,skus):
        return [row for row in [variant('N15-SKU-128',price=352000,stock=1)|{'product_id':'N15'},
                               variant('C15-SKU-128',price=223000,stock=13)|{'product_id':'C15'}] if row['sku'] in skus]
    def product(self,pid):return {'product_id':pid,'product_name':pid}
    def product_variants(self,pid):return self.variants(['N15-SKU-128' if pid=='N15' else 'C15-SKU-128'])
    def promotions(self,company):return []


class Model:
    def __init__(self,decisions):self.decisions=iter(decisions);self.calls=0
    async def plan(self,*args):self.calls+=1;return next(self.decisions)
    async def finalize(self,*args):raise AssertionError('검증 문장을 재출력하는 모델 호출은 제거됨')


def setup(monkeypatch,decisions):
    monkeypatch.setattr('backend.app.chat.read_once_retry',lambda engine,op:op(Repo()))
    model=Model(decisions)
    return ChatFlow(None,model),model


async def turn(flow,ctx,message):
    result=await flow.graph.ainvoke({'body':body(message),'context':ctx,'emit':lambda *args:None})
    ctx=copy.deepcopy(ctx);ctx['state']=result['state']
    ctx.setdefault('messages',[]).append({'user_message':message,'assistant_message':result['result'].message})
    ctx['messages']=ctx['messages'][-5:]
    return ctx,result['result']


@pytest.mark.parametrize('answer',['2개','2대','두 개','2'])
def test_reported_quantity_flow_and_shortage_preserves_sku(monkeypatch,answer):
    flow,model=setup(monkeypatch,[Decision(action='quote',target=Target(sku='N15-SKU-128'))])
    async def run():
        ctx={'state':{},'messages':[],'lists':[]}
        ctx,result=await turn(flow,ctx,'N15-SKU-128로 견적 내줘')
        assert result.status=='NEED_INPUT' and ctx['state']['selected_items'][0]['sku']=='N15-SKU-128'
        ctx,result=await turn(flow,ctx,answer)
        assert result.status=='OUT_OF_STOCK' and result.data['stock_issues'][0]['shortage_quantity']==1
        assert ctx['state']['selected_items'][0]['sku']=='N15-SKU-128'
        ctx,result=await turn(flow,ctx,'1개')
        assert result.status=='OK' and result.data['quote']['total']==352000
        assert not result.questions and model.calls==1
    asyncio.run(run())


def test_typo_confirmation_is_bound_to_original_sku(monkeypatch):
    flow,model=setup(monkeypatch,[Decision(action='quote',target=Target(sku='N15-SKU-128'))])
    async def run():
        ctx={'state':{},'messages':[],'lists':[]}
        ctx,_=await turn(flow,ctx,'N15-SKU-128로 견적 내줘')
        ctx,result=await turn(flow,ctx,'3ro')
        assert result.status=='NEED_INPUT' and '3개' in result.message
        assert ctx['state']['selected_items']==[{'sku':'N15-SKU-128'}]
        ctx,result=await turn(flow,ctx,'네')
        assert result.status=='OUT_OF_STOCK' and result.data['stock_issues'][0]['requested_quantity']==3
        assert model.calls==1
    asyncio.run(run())


def test_exact_sku_is_resolved_even_when_model_uses_name_field(monkeypatch):
    flow,_=setup(monkeypatch,[Decision(action='quote',target=Target(name='N15-SKU-128'))])
    async def run():
        ctx,result=await turn(flow,{'state':{},'messages':[],'lists':[]},'N15-SKU-128로 견적 내줘')
        assert result.status=='NEED_INPUT' and ctx['state']['selected_items']==[{'sku':'N15-SKU-128'}]
    asyncio.run(run())


def test_clear_new_request_can_change_product(monkeypatch):
    flow,_=setup(monkeypatch,[Decision(action='quote',target=Target(sku='N15-SKU-128')),
                              Decision(action='show_options',target=Target(name='Redmi 15C 5G'))])
    async def run():
        ctx={'state':{},'messages':[],'lists':[]}
        ctx,_=await turn(flow,ctx,'N15-SKU-128로 견적 내줘')
        ctx,result=await turn(flow,ctx,'일단 Redmi 15C 5G 옵션 보여줘')
        assert result.data['product']['product_id']=='C15'
        assert not ctx['state'].get('selected_items')
    asyncio.run(run())


def test_ambiguous_model_target_does_not_mutate_confirmed_selection(monkeypatch):
    flow,_=setup(monkeypatch,[Decision(action='quote',target=Target(name='Redmi 15C 5G'))])
    async def run():
        state={'constraints':{},'selected_items':[{'sku':'N15-SKU-128'}],
               'task':{'intent':'QUOTE','waiting_for':['quantity']}}
        ctx,result=await turn(flow,{'state':state,'messages':[],'lists':[]},'잘 모르겠는데')
        assert result.status=='NEED_INPUT'
        assert ctx['state']['selected_items']==state['selected_items'] and 'quote' not in (result.data or {})
    asyncio.run(run())


def test_partial_capacity_answer_and_preference_clear(monkeypatch):
    flow,_=setup(monkeypatch,[Decision(action='update_pending',values={'storage_gb':256},clear_fields=['colors'])])
    async def run():
        ctx={'state':{'constraints':{'colors':['검정'],'brands':['Xiaomi']},'task':{'intent':'QUOTE','waiting_for':['sku','quantity']}},'messages':[],'lists':[]}
        ctx,result=await turn(flow,ctx,'색상은 아무거나 256GB로')
        assert ctx['state']['constraints']=={'brands':['Xiaomi'],'storage_gb':256}
        assert ctx['state']['preferences']['colors']=='ANY' and not ctx['state'].get('selected_items')
    asyncio.run(run())


def test_multi_sku_quantities_remain_separate(monkeypatch):
    flow,_=setup(monkeypatch,[Decision(action='quote',targets=[Target(sku='N15-SKU-128',quantity=1,quantity_evidence='1개'),
        Target(sku='C15-SKU-128',quantity=2,quantity_evidence='2개')])])
    async def run():
        ctx,result=await turn(flow,{'state':{},'messages':[],'lists':[]},'N15-SKU-128 1개 C15-SKU-128 2개 견적')
        assert [i['quantity'] for i in result.data['quote']['items']]==[1,2]
    asyncio.run(run())


def test_ordinal_quote_uses_latest_and_does_not_confirm_representative(monkeypatch):
    flow,_=setup(monkeypatch,[Decision(action='quote',target=Target(position=2),values={'quantity':3},evidence={'quantity':'3대'})])
    class OptionsRepo(Repo):
        def product_variants(self,pid):return [variant('C15-SKU-128')|{'product_id':pid},variant('C15-SKU-256')|{'product_id':pid}]
    monkeypatch.setattr('backend.app.chat.read_once_retry',lambda engine,op:op(OptionsRepo()))
    async def run():
        ctx={'state':{},'messages':[],'lists':[{'items':[{'position':2,'product_id':'C15','product_name':'폰','representative_variant':{'sku':'AUTO'}}]}]}
        ctx,result=await turn(flow,ctx,'두 번째 제품으로 3대 견적 내줘')
        assert result.status=='NEED_INPUT' and len(result.data['variants'])==2
        assert ctx['state']['selected_product_ids']==['C15'] and not ctx['state'].get('selected_items')
    asyncio.run(run())
