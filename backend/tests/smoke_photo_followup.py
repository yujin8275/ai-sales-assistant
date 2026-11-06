import json
from uuid import uuid4
import httpx


def run():
    with httpx.Client(base_url='http://127.0.0.1:8000',timeout=75) as client:
        sid=client.post('/sessions',json={}).json()['data']['session']['session_id']
        def ask(message, expected='OK'):
            response=client.post('/chat',json={'session_id':sid,'request_id':str(uuid4()),'message':message})
            response.raise_for_status()
            result=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')][-1]
            assert result['status']==expected,result
            return result
        try:
            first=ask('1대당 100만 원 이하 삼성 휴대폰 추천해줘')
            ids={p['product_id'] for p in first['data']['recommendations']}
            second=ask('그중 사진 촬영에 적합한 제품은 뭐야?')
            after=second['data']['recommendations']
            assert {p['product_id'] for p in after}<=ids
            assert len(after)<=3
            assert second['data']['consultation']['constraints']['budget']['amount']==1000000
            assert all('카메라' in p['reasons'][0]['summary'] or '사진' in p['reasons'][0]['summary'] for p in after)
            print(json.dumps({'before':list(ids),'after':[p['product_id'] for p in after],
                'message':second['message'],'reasons':[p['reasons'][0]['summary'] for p in after],
                'sources':len(second['sources']),'warnings':second['warnings']},ensure_ascii=False),flush=True)
            third=ask('두 번째 제품으로 3대 견적 내줘','NEED_INPUT')
            assert third['data']['product']['product_id']==after[1]['product_id']
            assert 'recommendations' not in third['data']
            variant=next(v for v in third['data']['variants'] if v['stock_quantity']>=3)
            fourth=ask(variant['sku']+'로 3대 견적 내줘')
            quote=fourth['data']['quote']
            assert quote['items'][0]['quantity']==3
            assert quote['items'][0]['sku']==variant['sku']
            assert quote['total']==variant['sale_price']*3
            print(json.dumps({'ordinal_quote_product':third['data']['product']['product_name'],
                'option_count':len(third['data']['variants']),'sku':variant['sku'],
                'quantity':3,'total':quote['total'],'no_recommendation_rerun':True},ensure_ascii=False),flush=True)
        finally:
            client.post('/sessions/'+sid+'/reset',json={'request_id':str(uuid4())})


if __name__=='__main__':run()
