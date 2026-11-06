from backend.app.interpretation import explicit_action


def test_explicit_weight_budget_and_brand_are_preserved():
    action=explicit_action('100만원 이하 삼성 휴대폰 중 무게 180g 이하 제품 추천해줘',{},[])
    assert action.intent=='RECOMMEND'
    assert action.updates['max_weight_g']==180
    assert action.updates['budget']['amount']==1000000
    assert action.updates['brands']==['Samsung']


def test_numeric_display_and_battery_filters():
    action=explicit_action('화면 6.5인치 이상 배터리 5,000mAh 이상 추천',{},[])
    assert action.updates['min_display_inches']==6.5
    assert action.updates['min_battery_mah']==5000
