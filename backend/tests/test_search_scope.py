import pytest
from backend.app.planner import Decision,resolve,PlanningIssue


def context():
    return {'state':{'constraints':{'budget':{'amount':500000,'scope':'PER_UNIT'},
        'purpose':'카메라가 좋은','scope_product_ids':['OLD']},
        'task':{'intent':'RECOMMEND','waiting_for':[]}},
        'lists':[{'items':[{'product_id':'OLD','position':1}]}]}


@pytest.mark.parametrize('patch,evidence,message',[
    ({'budget':{'amount':1000000,'scope':'PER_UNIT'}},{'budget':'100만원'},'예산을 100만원까지 늘려서 찾아줘'),
    ({'brands':['Samsung']},{'brands':'삼성'},'삼성으로 찾아줘'),
    ({'max_weight_g':180},{'max_weight_g':'180g'},'180g 이하로 찾아줘')])
def test_updated_conditions_search_catalogue_without_persisted_list(patch,evidence,message):
    state,action=resolve(Decision(action='recommend',values=patch,evidence=evidence),context(),message,[],[])
    assert 'scope_product_ids' not in state['constraints']
    assert state['constraints']['purpose']=='카메라가 좋은'
    assert action.search_product_ids is None and not action.within_latest


def test_list_scope_is_for_one_execution_only():
    ctx=context()
    state,action=resolve(Decision(action='recommend',scope='referenced_list',scope_reference='그중'),ctx,'그중 추천해줘',[],[])
    assert action.search_product_ids==['OLD'] and action.within_latest
    assert 'scope_product_ids' not in state['constraints']
    ctx['state']=state
    state,action=resolve(Decision(action='recommend'),ctx,'카메라가 좋은 핸드폰 추천해줘',[],[])
    assert action.search_product_ids is None


def test_completed_recommendation_patch_is_fresh_search():
    state,action=resolve(Decision(action='update_pending',values={'budget':{'amount':1000000}},
        evidence={'budget':'100만원'}),context(),'100만원까지 늘려줘',[],[])
    assert action.intent=='RECOMMEND' and not action.within_latest
    assert 'scope_product_ids' not in state['constraints']


def test_repeated_confirmed_value_is_not_a_new_change():
    ctx=context();ctx['state']['constraints']['quantity']=3
    state,action=resolve(Decision(action='recommend',values={'quantity':3}),ctx,'다시 추천해줘',[],[])
    assert state['constraints']['quantity']==3 and action.search_product_ids is None


@pytest.mark.parametrize('reference',['','그중','카메라가 좋은'])
def test_model_cannot_reuse_past_or_nonreferential_scope(reference):
    state,action=resolve(Decision(action='recommend',scope='referenced_list',scope_reference=reference),
        context(),'카메라가 좋은 핸드폰 추천해줘',[],[])
    assert action.search_product_ids is None and not action.within_latest
