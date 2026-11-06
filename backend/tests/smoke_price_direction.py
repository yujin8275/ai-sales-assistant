import asyncio
from uuid import uuid4
from backend.app.chat import ChatFlow
from backend.app.models import ChatRequest
from backend.app.repository import make_engine


async def run():
    engine=make_engine()
    try:
        flow=ChatFlow(engine)
        context={'state':{'constraints':{'brands':['Samsung'],'budget':{'amount':1000000,'scope':'PER_UNIT'}},
                         'task':{'intent':'RECOMMEND','waiting_for':[]}},'messages':[],'lists':[]}
        graph=await asyncio.wait_for(flow.graph.ainvoke({'body':ChatRequest(session_id=uuid4(),request_id=uuid4(),
            message='100만원 이상 중에서 카메라 좋은 모델'),'context':context,'emit':lambda *args:None}),120)
        result=graph['result'];budget=graph['state']['constraints']['budget']
        print('status',result.status,'budget',budget,flush=True)
        assert result.status=='OK' and budget['comparison']=='GTE'
        products=result.data['recommendations']
        assert products and all(p['price_from']>=1000000 for p in products)
        assert result.follow_up and result.follow_up['options']
        print('products',[(p['product_name'],p['price_from']) for p in products],flush=True)
        print('excluded',result.data['excluded_products'],flush=True)
        print('PRICE_DIRECTION_CHAIN_PASS',flush=True)
    finally:engine.dispose()


if __name__=='__main__':asyncio.run(run())
