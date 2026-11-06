"""사용자가 보고한 대화를 실제 모델·HTTP 경로로 재현한다."""
import json
from uuid import uuid4
import httpx


def run():
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=75) as client:
        created=client.post('/sessions',json={}).json()
        sid=created['data']['session']['session_id']
        def ask(message):
            response=client.post('/chat',json={'session_id':sid,'request_id':str(uuid4()),'message':message})
            response.raise_for_status()
            results=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
            result=results[-1]
            assert result['status']!='ERROR',result
            data=result.get('data') or {}
            print(json.dumps({'input':message,'status':result['status'],'message':result['message'],
                'product':data.get('product',{}).get('product_id'),'variants':len(data.get('variants',[])),
                'constraints':data.get('consultation',{}).get('constraints')},ensure_ascii=False),flush=True)
            return result
        try:
            first=ask('50만원 이하 휴대폰 추천해줘')
            assert first['data']['consultation']['constraints']=={'budget':{'amount':500000,'scope':'PER_UNIT'}}
            second=ask('Redmi 15C 5G(RM-15C)의 전체 옵션과 재고를 보여줘')
            assert second['data']['product']['product_id']=='RM-15C' and second['data']['variants']
            third=ask('갤럭시 S26+ 색상 어떤 게 있어?')
            assert third['data']['product']['product_id']=='SAM002'
            assert 'recommendations' not in third['data']
            assert len({v['color'] for v in third['data']['variants']})>1
            fourth=ask('예산 150만원까지 상향한다')
            assert fourth['data']['consultation']['constraints']=={'budget':{'amount':1500000,'scope':'PER_UNIT'}}
            print('REPORTED_CONVERSATION_PASS',flush=True)
        finally:
            client.post('/sessions/'+sid+'/reset',json={'request_id':str(uuid4())})


if __name__=='__main__':run()
