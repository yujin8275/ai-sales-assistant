import asyncio
import pytest
from backend.app.interpretation import explicit_action
from backend.app.knowledge import extract_evidence,answer_product_question
from backend.app.models import ToolResult
from backend.app.tools import BusinessError
from backend.tests.test_chat import body

HIT={'product_id':'SAM012','chunk_id':'c','document_id':'d','distance':.5,
     'metadata':{'source_file':'Samsung_제품설명서.pdf','page_number':12},
     'content':'제품 특징\n• Snapdragon 8 Elite for Galaxy 프로세서\n• 3배 광학 줌 및 최대 30배 디지털 줌\n제품 장단점\n장점과 단점이 섞인 표'}
CATALOGUE=[{'product_id':'SAM012','product_name':'Galaxy S25'}]


def test_named_advantages_are_knowledge_not_recommendation():
    action=explicit_action('갤럭시 S25 장점 알려줘',{},CATALOGUE)
    assert action.intent=='KNOWLEDGE' and action.product_ids==['SAM012']


def test_features_exclude_merged_advantage_disadvantage_table():
    evidence=extract_evidence([HIT],'장점')
    assert len(evidence)==2 and all('섞인' not in e['text'] for e in evidence)


def test_sources_and_answers_are_selected_from_retrieved_evidence(monkeypatch):
    class Repo:
        def product(self,pid):return {'product_id':pid,'product_name':'Galaxy S25'}
    class Model:
        async def select_evidence(self,query,evidence):return [1]
    async def search(self,query,ids,*args):
        assert ids==['SAM012']
        return ToolResult(status='OK',data={'hits':[HIT],'has_evidence':True})
    monkeypatch.setattr('backend.app.knowledge.read_once_retry',lambda engine,op:op(Repo()))
    monkeypatch.setattr('backend.app.knowledge.RagTool.search_product_documents',search)
    result=asyncio.run(answer_product_question(None,Model(),body('갤럭시 S25 장점 알려줘'),'SAM012'))
    assert result.evidence_status=='FOUND'
    assert '3배 광학 줌' in result.message and 'recommendations' not in result.data
    assert result.sources[0]['page_number']==12
    assert result.data['explanation']['points'][0]['source_ids']==['source-1']


def test_missing_evidence_does_not_invent_advantages(monkeypatch):
    class Repo:
        def product(self,pid):return {'product_id':pid,'product_name':'Galaxy S25'}
    async def search(*args):return ToolResult(status='OK',data={'hits':[],'has_evidence':False})
    monkeypatch.setattr('backend.app.knowledge.read_once_retry',lambda engine,op:op(Repo()))
    monkeypatch.setattr('backend.app.knowledge.RagTool.search_product_documents',search)
    result=asyncio.run(answer_product_question(None,object(),body('장점'),'SAM012'))
    assert result.evidence_status=='NOT_FOUND' and not result.sources
