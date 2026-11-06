import asyncio
from uuid import uuid4
import pytest
from backend.app.models import Budget,Response,RecommendFilters
from backend.app.recommendation import prepare_candidates,recommend
from backend.tests.test_recommend import SearchRepo
from backend.tests.test_quote import variant


@pytest.mark.parametrize('op,prices', [('GTE',[100,101]),('GT',[101]),('LTE',[99,100]),('LT',[99]),('RANGE',[100,101])])
def test_price_boundaries(op,prices):
    budget=Budget(amount=100,comparison=op,**({'upper_amount':101} if op=='RANGE' else {}))
    assert [p for p in [99,100,101] if budget.accepts(p,1)]==prices
    assert [p for p in [99,100,101] if budget.accepts(p*3,3)]==prices


def test_invalid_range():
    with pytest.raises(ValueError):Budget(amount=200,comparison='RANGE',upper_amount=100)


def test_excluded_names_respect_price_and_stock(monkeypatch):
    repo=SearchRepo([variant('LOW',price=99,stock=0)|{'product_id':'LOW'},
                     variant('HIGH',price=101,stock=0)|{'product_id':'HIGH'}])
    filters=RecommendFilters(budget={'amount':100,'comparison':'GTE'})
    candidates,_,excluded=prepare_candidates(repo,filters)
    assert not candidates and [p['product_name'] for p in excluded]==['HIGH']
    monkeypatch.setattr('backend.app.recommendation.read_once_retry',lambda engine,op:op(repo))
    from backend.app.models import RecommendRequest
    result=asyncio.run(recommend(None,RecommendRequest(request_id=uuid4(),filters=filters)))
    assert 'HIGH' in result.warnings[0] and 'LOW' not in result.warnings[0]
    assert result.follow_up and result.status=='NO_MATCH'


def test_followup_does_not_compete_with_required_question():
    result=Response(request_id=uuid4(),status='NEED_INPUT',message='수량?',questions=[{'missing_fields':['quantity']}])
    assert result.follow_up is None
