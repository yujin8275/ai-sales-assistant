from fastapi.testclient import TestClient
from backend.app.main import app


def test_home_uses_real_brand_rankings(monkeypatch):
    class Repo:
        def catalogue(self):return [{'brand':'Apple'},{'brand':'Xiaomi'},{'brand':'Samsung'}]
    calls=[]
    def ranking(self,filters,limit):
        from backend.app.models import ToolResult
        calls.append((filters.brands,limit))
        return ToolResult(status='OK',data={'sales_ranking':[{'brand':filters.brands[0],'rank':1}]})
    monkeypatch.setattr('backend.app.main.read_once_retry',lambda engine,op:op(Repo()))
    monkeypatch.setattr('backend.app.main.ProductTool.get_sales_ranking',ranking)
    monkeypatch.setattr('backend.app.main.ProductTool.home_ranking',lambda self:__import__('backend.app.models',fromlist=['ToolResult']).ToolResult(status='OK',data={'sales_ranking':[]}))
    app.state.engine=object()
    response=TestClient(app).get('/home')
    assert response.status_code==200
    assert [p['brand'] for p in response.json()['data']['brand_leaders']]==['Xiaomi','Samsung','Apple']
    assert all(limit==1 for _,limit in calls)
