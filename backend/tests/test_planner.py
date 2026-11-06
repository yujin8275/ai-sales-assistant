import copy
import pytest
from backend.app.planner import Decision,Target,pending_answer,resolve,PlanningIssue,quantity_value


def context():
    return {'state':{'constraints':{'budget':{'amount':500000}},
        'selected_items':[{'sku':'RM-N15-GB-6-128'}],'selected_product_ids':['RM-N15'],
        'task':{'intent':'QUOTE','waiting_for':['quantity']}},'messages':[],'lists':[]}


@pytest.mark.parametrize('text', ['2개','2대','두 개','두개요','2','수량은 2개','두 개로 해줘'])
def test_quantity_answers_only_update_quantity(text):
    ctx=context();before=copy.deepcopy(ctx)
    decision=pending_answer(text,ctx['state'])
    state,action=resolve(decision,ctx,text,[],[])
    assert state['selected_items']==[{'sku':'RM-N15-GB-6-128','quantity':2}]
    assert action.intent=='QUOTE' and state['constraints']['quantity']==2
    assert ctx==before


def test_typo_asks_confirmation_without_switching_product():
    ctx=context();before=copy.deepcopy(ctx)
    with pytest.raises(PlanningIssue) as exc:
        resolve(pending_answer('3ro',ctx['state']),ctx,'3ro',[],[])
    assert exc.value.hint==3 and ctx==before


def test_yes_without_quantity_confirmation_does_not_mean_four():
    ctx=context()
    assert quantity_value('네') is None and quantity_value('네 개')==4
    assert pending_answer('네',ctx['state']).action=='clarify'


def test_partial_update_cannot_change_target():
    with pytest.raises(ValueError):Decision(action='update_pending',target=Target(name='다른 폰'),values={'quantity':2})


def test_pending_quantity_rejects_unrelated_changes():
    ctx=context()
    with pytest.raises(PlanningIssue):resolve(Decision(action='update_pending',values={'brands':['Samsung']}),ctx,'2개',[],[])
    assert ctx['state']['selected_items'][0]['sku']=='RM-N15-GB-6-128'


def test_invented_product_not_accepted():
    with pytest.raises(PlanningIssue):resolve(Decision(action='quote',target=Target(name='Redmi 15C')),
        context(),'2개',[{'product_id':'RM-15C','product_name':'Redmi 15C'}],[])


def test_explicit_new_request_can_switch_to_named_product():
    state,action=resolve(Decision(action='show_options',target=Target(name='갤럭시 S25')),context(),
        '일단 갤럭시 S25 옵션 보여줘',[{'product_id':'SAM012','product_name':'Galaxy S25'}],[])
    assert action.intent=='DETAILS' and state['selected_product_ids']==['SAM012']
    assert not state.get('selected_items')


def test_latest_scope_is_exact_and_empty_list_stays_empty():
    ctx=context();ctx['lists']=[{'items':[{'product_id':'A','position':1}]}]
    state,action=resolve(Decision(action='recommend',scope='referenced_list',scope_reference='그중'),ctx,'그중에서 추천',[],[])
    assert action.search_product_ids==['A'] and 'scope_product_ids' not in state['constraints']
    ctx['lists']=[{'items':[]}]
    state,action=resolve(Decision(action='recommend',scope='referenced_list',scope_reference='그중'),ctx,'그중에서 추천',[],[])
    assert action.search_product_ids==[]


def test_ordinal_resolves_latest_not_previous():
    ctx=context();ctx['lists']=[{'items':[{'position':2,'product_id':'NEW'}]}, {'items':[{'position':2,'product_id':'OLD'}]}]
    state,action=resolve(Decision(action='quote',target=Target(position=2),values={'quantity':3},evidence={'quantity':'3대'}),
        ctx,'두 번째로 3대 견적',[],[])
    assert state['selected_product_ids']==['NEW'] and action.intent=='QUOTE'


def test_no_pending_task_does_not_reuse_last_intent_blindly():
    with pytest.raises(PlanningIssue):resolve(Decision(action='update_pending',values={'quantity':2}),
        {'state':{},'lists':[]},'2개',[],[])


def test_sku_digits_cannot_be_quantity_evidence():
    decision=Decision(action='quote',target=Target(sku='RM-N15-GB-6-128'),
        values={'quantity':1},evidence={'quantity':'1'})
    with pytest.raises(PlanningIssue):resolve(decision,context(),'RM-N15-GB-6-128로 견적 내줘',[],
        [{'sku':'RM-N15-GB-6-128','product_id':'RM-N15'}])


def test_recommendation_does_not_change_selected_product_from_generic_target():
    decision=Decision(action='recommend',targets=[Target(name='휴대폰')])
    assert not decision.targets
