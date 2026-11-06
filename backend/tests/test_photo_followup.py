from backend.app.interpretation import explicit_action, grounded_action
from backend.app.models import ChatAction
from backend.app.recommendation import purpose_reason


def test_photo_followup_explicitly_locks_latest_list_and_purpose():
    message='그중 사진 촬영에 적합한 제품은 뭐야?'
    action=explicit_action(message,{},[])
    assert action.intent=='RECOMMEND' and action.within_latest
    assert action.updates=={'purpose':message}


def test_per_unit_budget_is_not_confirmed_purchase_quantity():
    action=explicit_action('1대당 100만 원 이하 삼성 휴대폰 추천해줘',{},[])
    assert action.updates['budget']['amount']==1000000
    assert 'quantity' not in action.updates


def test_photo_reason_contains_verified_camera_facts_not_generic_stock():
    product={'specs':{'cameras':[{'camera_type':'후면 메인','resolution_mp':50,'ois':True,'max_zoom':3}]}}
    reason=purpose_reason(product,'사진 촬영')
    assert '50MP' in reason and 'OIS 지원' in reason and '3배' in reason
    assert '광학' not in reason


def test_no_camera_specs_does_not_invent_quality():
    reason=purpose_reason({'specs':{'cameras':[]}},'사진')
    assert '판단하기 어렵' in reason


def test_latest_scope_does_not_depend_on_model_boolean():
    action=grounded_action(ChatAction(intent='RECOMMEND',within_latest=False),'그중 삼성만 보여줘')
    assert action.within_latest is True
