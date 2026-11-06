import asyncio
import pytest
from backend.app.interpretation import explicit_action
from backend.app.chat import ChatFlow,resolve_targets
from backend.app.models import ChatAction
from backend.tests.test_chat import body,graph,Model
from backend.tests.test_quote import Repo,variant


@pytest.mark.parametrize('message',['두 번째 제품으로 3대 견적 내줘','두번째로 3대 견적','2번째 제품으로 3대 견적','2번 상품 3대 견적'])
def test_quote_intent_and_ordinal_are_server_resolved(message):
    action=explicit_action(message,{},[])
    assert action.intent=='QUOTE' and action.positions==[2] and action.updates=={'quantity':3}


def test_user_ordinal_overrides_invented_model_position():
    context={'lists':[{'items':[{'position':1,'product_id':'OLD'},{'position':2,'product_id':'LATEST'}]}]}
    assert resolve_targets(ChatAction(intent='QUOTE',positions=[1]),context,'두 번째 제품으로 3대 견적 내줘')==['LATEST']



