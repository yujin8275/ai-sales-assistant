import asyncio,json
from uuid import uuid4
import httpx
from backend.app.rag import RagTool
from backend.app.repository import make_engine


def run():
    engine=make_engine()
    try:
        found=asyncio.run(RagTool(engine).search_product_documents('갤럭시 S25 장점 알려줘',['SAM012']))
        print(json.dumps({'rag_hits':len(found.data['hits']),'hits':[{
            'product_id':h['product_id'],'distance':h['distance'],'method':h['retrieval_method'],
            'file':h['metadata']['source_file'],'page':h['metadata']['page_number']} for h in found.data['hits']]},ensure_ascii=False),flush=True)
        assert found.data['hits']
    finally:engine.dispose()
    with httpx.Client(base_url='http://127.0.0.1:8000',timeout=75) as client:
        sid=client.post('/sessions',json={}).json()['data']['session']['session_id']
        try:
            response=client.post('/chat',json={'session_id':sid,'request_id':str(uuid4()),'message':'갤럭시 S25 장점 알려줘'})
            response.raise_for_status()
            result=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')][-1]
            assert result['status']=='OK' and result['evidence_status']=='FOUND',result
            assert result['data']['product']['product_id']=='SAM012'
            assert 'recommendations' not in result['data'] and result['sources'][0]['page_number']==12
            print(json.dumps({'message':result['message'],'sources':result['sources']},ensure_ascii=False),flush=True)
        finally:client.post('/sessions/'+sid+'/reset',json={'request_id':str(uuid4())})


if __name__=='__main__':run()
