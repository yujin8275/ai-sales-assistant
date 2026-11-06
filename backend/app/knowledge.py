import asyncio
import re

from backend.app.models import Response
from backend.app.repository import read_once_retry
from backend.app.rag import RagTool
from backend.app.tools import BusinessError


def extract_evidence(hits, query):
    evidence=[]
    for hit in hits:
        content=hit['content']
        if '단점' in query:
            # 현재 PDF의 장단점 표가 행 단위로 섞여 추출된 경우 단점을 임의 분리하지 않는다.
            continue
        clean=content.split('제품 장단점')[0]
        if '제품 특징' in clean:
            clean=clean.split('제품 특징',1)[1]
        for line in clean.splitlines():
            line=line.strip().removeprefix('•').strip()
            if not 12<=len(line)<=240 or re.search(r'상품코드|기종명|문서번호|설명서|[\d,]+\s*원|판매가|재고|할인',line):
                continue
            if not any(e['text']==line for e in evidence):
                evidence.append({'text':line,'hit':hit})
    return evidence


async def answer_product_question(engine, model, body, product_id):
    product=await asyncio.to_thread(read_once_retry,engine,lambda repo:repo.product(product_id))
    if product is None:
        return Response(request_id=body.request_id,session_id=body.session_id,status='NOT_FOUND',message='등록된 상품을 찾을 수 없습니다.')
    result=await RagTool(engine,model).search_product_documents(body.message,[product_id])
    evidence=extract_evidence(result.data['hits'],body.message)
    if not evidence:
        return Response(request_id=body.request_id,session_id=body.session_id,status='OK',data={'product':product},
            message=product['product_name']+'의 질문에 답할 만한 명확한 설명서 근거를 찾지 못했습니다. 등록 사양은 확인할 수 있지만 장단점을 추측하지 않겠습니다.',evidence_status='NOT_FOUND')
    indices=await model.select_evidence(body.message,evidence)
    if not indices or len(set(indices))!=len(indices) or any(type(i)is not int or not 0<=i<len(evidence) for i in indices):
        raise BusinessError('MODEL_ERROR','설명 근거를 확인할 수 없습니다. 다시 요청해 주세요.',503)
    selected=[evidence[i] for i in indices]
    sources=[]
    points=[]
    for entry in selected:
        hit=entry['hit']
        source=next((s for s in sources if s['source_file']==hit['metadata']['source_file'] and s['page_number']==hit['metadata']['page_number']),None)
        if source is None:
            source={'source_id':'source-'+str(len(sources)+1),'source_file':hit['metadata']['source_file'],
                    'page_number':hit['metadata']['page_number'],'summary':entry['text']}
            sources.append(source)
        points.append({'text':entry['text'],'source_ids':[source['source_id']]})
    message=product['product_name']+'의 설명서에서 확인한 특징입니다.\n\n'+'\n'.join('• '+p['text'] for p in points)
    return Response(request_id=body.request_id,session_id=body.session_id,status='OK',message=message,
        data={'product':product,'explanation':{'product_id':product_id,'points':points}},
        sources=sources,evidence_status='FOUND')
