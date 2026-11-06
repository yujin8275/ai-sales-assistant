"""실제 모델 + Tool을 쓰되 상담 DB에는 쓰지 않는 연속 대화 평가."""
import asyncio,copy,json,time
from uuid import uuid4
from backend.app.chat import ChatFlow
from backend.app.models import ChatRequest
from backend.app.repository import make_engine
from backend.app.chat_model import ChatModel


class ObservedModel(ChatModel):
    async def _request(self,schema,prompt,data,validate):
        def measured(content):
            if 'current_message' in data:print('MODEL_JSON '+content,flush=True)
            return validate(content)
        return await super()._request(schema,prompt,data,measured)

    async def plan(self,message,context):
        result=await super().plan(message,context)
        print(json.dumps({'decision':result.model_dump(exclude_defaults=True)},ensure_ascii=False),flush=True)
        return result


async def run():
    engine=make_engine();flow=ChatFlow(engine,ObservedModel())
    ctx={'state':{},'messages':[],'lists':[]}
    async def ask(message):
        nonlocal ctx
        start=time.monotonic()
        graph=await asyncio.wait_for(flow.graph.ainvoke({'body':ChatRequest(session_id=uuid4(),request_id=uuid4(),message=message),
            'context':ctx,'emit':lambda *args:None}),120)
        result=graph['result']
        ctx['state']=graph['state']
        ctx['messages']=(ctx['messages']+[{'user_message':message,'assistant_message':result.message}])[-5:]
        displayed=(result.data or {}).get('recommendations') or (result.data or {}).get('sales_ranking')
        if displayed:ctx['lists']=([{'items':displayed}]+ctx['lists'])[:2]
        print(json.dumps({'input':message,'seconds':round(time.monotonic()-start,2),'status':result.status,'message':result.message,
            'selected':ctx['state'].get('selected_items'),'task':ctx['state'].get('task')},ensure_ascii=False),flush=True)
        return result
    try:
        first=await ask('50만원 이하 휴대폰 추천해줘')
        assert first.status=='OK' and first.data['recommendations']
        result=await ask('Redmi Note 15 5G(RM-N15)의 전체 옵션과 재고를 보여줘')
        assert result.data['product']['product_id']=='RM-N15'
        result=await ask('RM-N15-GB-6-128로 견적 내줘')
        assert result.status=='NEED_INPUT' and ctx['state']['selected_items'][0]['sku']=='RM-N15-GB-6-128'
        result=await ask('3ro')
        assert result.status=='NEED_INPUT' and ctx['state']['selected_items'][0]['sku']=='RM-N15-GB-6-128'
        for answer in ('2개','두 개','2','1개'):
            result=await ask(answer)
            assert ctx['state']['selected_items'][0]['sku']=='RM-N15-GB-6-128'
            assert result.status==('OK' if answer=='1개' else 'OUT_OF_STOCK')
        assert result.data['quote']['items'][0]['quantity']==1
        result=await ask('일단 갤럭시 S25 장점 알려줘')
        assert result.status=='OK' and result.evidence_status=='FOUND' and result.data['product']['product_id']=='SAM012'
        print('PLANNER_V2_REPORTED_CHAIN_PASS',flush=True)
        ctx={'state':{},'messages':[],'lists':[]}
        result=await ask('1대당 100만 원 이하 삼성 휴대폰 추천해줘')
        assert result.status=='OK' and ctx['state']['constraints']['brands']==['Samsung']
        original={p['product_id'] for p in result.data['recommendations']}
        result=await ask('그중 사진 촬영에 적합한 제품은 뭐야?')
        assert result.status=='OK' and {p['product_id'] for p in result.data['recommendations']}<=original
        second=result.data['recommendations'][1]['product_id']
        result=await ask('두 번째 제품으로 3대 견적 내줘')
        assert result.status=='NEED_INPUT' and ctx['state']['selected_product_ids']==[second]
        assert 'recommendations' not in result.data and result.data['variants']
        sku=result.data['variants'][0]['sku']
        result=await ask(sku+'로 견적 내줘')
        assert result.status in ('OK','OUT_OF_STOCK') and ctx['state']['selected_items'][0]['sku']==sku
        assert ctx['state']['selected_items'][0]['quantity']==3
        result=await ask('갤럭시 S25와 갤럭시 S26 배터리를 비교해줘')
        assert result.status=='OK' and set(ctx['state']['selected_product_ids'])=={'SAM012','SAM003'}
        result=await ask('휴대폰 판매 순위 알려줘')
        assert result.status=='OK' and result.data['sales_ranking']
        ctx={'state':{},'messages':[],'lists':[]}
        await ask('50만원 이하 휴대폰 추천해줘')
        result=await ask('예산 150만원까지 상향한다')
        assert result.status=='OK' and ctx['state']['constraints']['budget']['amount']==1500000
        print('PLANNER_V2_FOLLOWUP_CHAIN_PASS',flush=True)
        ctx={'state':{'constraints':{'budget':{'amount':500000,'scope':'PER_UNIT'},'scope_product_ids':['RM-N15']}},'messages':[],
             'lists':[{'items':[{'product_id':'RM-N15','product_name':'Redmi Note 15 5G','position':1}]}]}
        result=await ask('그중 카메라가 좋은 핸드폰 추천해줘')
        assert result.status=='OK' and {p['product_id'] for p in result.data['recommendations']}=={'RM-N15'}
        assert 'scope_product_ids' not in ctx['state']['constraints']
        result=await ask('카메라가 좋은 핸드폰 추천해줘')
        assert result.status=='OK' and 'scope_product_ids' not in result.data['applied_filters']
        result=await ask('예산을 100만원까지 늘려서 찾아줘')
        assert result.status=='OK' and result.data['applied_filters']['budget']['amount']==1000000
        assert 'scope_product_ids' not in result.data['applied_filters']
        assert any(p['price_from']>500000 for p in result.data['recommendations'])
        print('PLANNER_V2_SCOPE_REEXPANSION_PASS',flush=True)
    finally:engine.dispose()


if __name__=='__main__':asyncio.run(run())
