from backend.app.models import ChatAction
from backend.app.interpretation import explicit_action, grounded_action, mentioned_products

CATALOGUE = [
    {'product_id':'SAM001','product_name':'Galaxy S26 Ultra'},
    {'product_id':'SAM002','product_name':'Galaxy S26+'},
    {'product_id':'SAM003','product_name':'Galaxy S26'},
    {'product_id':'RM-15C','product_name':'Redmi 15C 5G'},
]


def test_color_question_targets_exact_model_not_recommendations():
    a=explicit_action('갤럭시 S26+ 색상 어떤 게 있어?', {}, CATALOGUE)
    assert a.intent=='DETAILS' and a.product_ids==['SAM002']
    assert a.updates=={}


def test_option_button_text_does_not_need_llm_interpretation():
    a=explicit_action('Redmi 15C 5G(RM-15C)의 전체 옵션과 재고를 보여줘', {}, CATALOGUE)
    assert a.intent=='DETAILS' and a.product_ids==['RM-15C']


def test_budget_increase_replaces_exact_amount():
    a=explicit_action('예산 150만원까지 상향한다', {'constraints':{'budget':{'amount':500000,'scope':'PER_UNIT'}}}, CATALOGUE)
    assert a.intent=='RECOMMEND' and a.updates=={'budget':{'amount':1500000,'scope':'PER_UNIT'}}


def test_phantom_preferences_are_discarded():
    a=grounded_action(ChatAction(intent='RECOMMEND',updates={'brands':['Samsung','Xiaomi'], 'colors':[],
        'purpose':'phone_5g','budget':{'amount':500000}}),'50만원 이하 휴대폰 추천해줘')
    assert a.updates=={'budget':{'amount':500000,'scope':'PER_UNIT'}}


def test_purpose_and_explicit_brand_retained_for_budget_recommendation():
    a=explicit_action('삼성 휴대폰 50만원 이하 배터리 좋은 걸로 추천', {}, CATALOGUE)
    assert a.updates['brands']==['Samsung'] and '배터리' in a.updates['purpose']


def test_specific_models_and_plus_are_not_confused():
    assert mentioned_products('갤럭시 S26 울트라 색상', CATALOGUE)==['SAM001']
    assert mentioned_products('갤럭시 S26 플러스 색상', CATALOGUE)==['SAM002']


def test_color_preference_waiver_does_not_clear_other_fields():
    a=grounded_action(ChatAction(intent='UNKNOWN',clear_fields=['colors','brands','budget']), '색상은 아무거나')
    assert a.clear_fields==['colors']



