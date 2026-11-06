import asyncio,json,time,os
from backend.app.chat_model import ChatModel


async def run():
    context={'state':{'constraints':{'brands':['Samsung'],'budget':{'amount':1000000,'scope':'PER_UNIT'}}},
             'messages':[], 'lists':[{'items':[{'position':1,'product_id':'SAM012','product_name':'Galaxy S25'},
                                              {'position':2,'product_id':'SAM003','product_name':'Galaxy S26'}]}]}
    cases=[('두 번째 제품으로 3대 견적 내줘',lambda a:a.action=='quote' and a.targets[0].position==2 and a.values.get('quantity')==3),
           ('그중 사진 촬영에 적합한 제품은 뭐야?',lambda a:a.action=='recommend' and a.scope=='referenced_list' and bool(a.values.get('purpose'))),
           ('갤럭시 S25 장점 알려줘',lambda a:a.action=='explain' and a.targets[0].name=='갤럭시 S25'),
           ('예산 150만원까지 상향한다',lambda a:a.values.get('budget',{}).get('amount')==1500000)]
    for name in os.getenv('CHAT_BENCHMARK_MODELS',ChatModel().chat_model).split(','):
        model=ChatModel();model.chat_model=name
        for question,check in cases:
            start=time.monotonic()
            try:
                action=await model.plan(question,context)
                result={'pass':check(action),'action':action.model_dump()}
            except Exception as exc:result={'pass':False,'error':type(exc).__name__}
            print(json.dumps({'model':name,'question':question,'seconds':round(time.monotonic()-start,2),**result},ensure_ascii=False),flush=True)


if __name__=='__main__':asyncio.run(run())
