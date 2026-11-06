from datetime import date
import pytest
from backend.app.models import ProductFilters
from backend.app.tools import ProductTool, BusinessError
from backend.app.interpretation import explicit_action
from backend.tests.test_recommend import SearchRepo
from backend.tests.test_quote import variant


class RankingRepo(SearchRepo):
    def sales(self, ids):
        return [{'product_id':'A','sales_quantity_3m':100,'sales_reference_date':date(2026,11,3),'reference_date_count':1},
                {'product_id':'B','sales_quantity_3m':200,'sales_reference_date':date(2026,11,3),'reference_date_count':1}]


def repo():
    return RankingRepo([variant('A1')|{'product_id':'A'},variant('B1',price=300)|{'product_id':'B'}])


def test_sales_question_uses_ranking_without_invented_preferences():
    action=explicit_action('휴대폰 판매 순위를 알려줘',{},[])
    assert action.intent=='RANKING' and action.updates=={}


def test_rank_cards_include_actual_sales_date_and_options():
    rows=ProductTool(repo()).get_sales_ranking(ProductFilters()).data['sales_ranking']
    assert [(r['rank'],r['product_id'],r['sales_quantity_3m']) for r in rows]==[(1,'B',200),(2,'A',100)]
    assert rows[0]['representative_variant']['sku']=='B1'
    assert rows[0]['sales_reference_date']==date(2026,11,3)


@pytest.mark.parametrize('mixed',['within_product','between_products'])
def test_different_sales_periods_not_ranked_together(mixed):
    instance=repo()
    base=instance.sales([])
    if mixed=='within_product':base[0]['reference_date_count']=2
    else:base[0]['sales_reference_date']=date(2026,10,3)
    instance.sales=lambda ids:base
    with pytest.raises(BusinessError,match='기준일'):
        ProductTool(instance).get_sales_ranking(ProductFilters())
