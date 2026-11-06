import asyncio
import re


def purpose_reason(product, purpose):
    specs = product['specs']
    if purpose and re.search(r'사진|촬영|카메라', purpose):
        cameras = specs.get('cameras', [])
        facts = []
        for camera in cameras:
            parts = [camera.get('camera_type') or '카메라']
            if camera.get('resolution_mp') is not None: parts.append(f"{camera['resolution_mp']}MP")
            if camera.get('ois') is True: parts.append('OIS 지원')
            if camera.get('ois') is False: parts.append('OIS 미지원')
            if camera.get('max_zoom') is not None: parts.append(f"등록 최대 줌 {camera['max_zoom']}배")
            facts.append(' · '.join(parts))
        return '사진 촬영 비교 근거: ' + '; '.join(facts) if facts else '등록된 카메라 사양이 없어 사진 촬영 적합성을 판단하기 어렵습니다.'
    if purpose and '배터리' in purpose and specs.get('battery_mah'):
        return f"등록 배터리 용량은 {specs['battery_mah']:,}mAh입니다. 실제 사용 시간은 사용 환경에 따라 다릅니다."
    return '등록 사양·가격·재고가 지정한 구매 조건을 충족합니다.'

from backend.app.models import ProductFilters, QuoteItem, Response
from backend.app.rag import OllamaClient, RagTool
from backend.app.repository import read_once_retry
from backend.app.tools import ProductTool, QuoteTool


def prepare_candidates(repo, filters):
    product_filters = ProductFilters.model_validate(filters.model_dump(
        exclude={"purpose", "budget", "card_company"}, exclude_none=True))
    search = ProductTool(repo).search_products(product_filters)
    candidates = search.data["candidates"]
    offers = [QuoteItem(sku=v["sku"], quantity=filters.quantity)
              for c in candidates for v in c["variants"]]
    prices = QuoteTool(repo).price_candidates(offers, filters.card_company).data["prices"] if offers else []
    accepted = {}
    for price in prices:
        if filters.budget is None or filters.budget.accepts(price['total'],filters.quantity):
            accepted[price["sku"]] = price
    qualified = []
    for candidate in candidates:
        variants = [v for v in candidate["variants"] if v["sku"] in accepted]
        if not variants:
            continue
        variant = min(variants, key=lambda v: (v["sale_price"], v["sku"]))
        qualified.append(candidate | {"variants": variants, "representative": variant,
                                      "price": accepted[variant["sku"]]})
    sales = {r["product_id"]: r["sales_quantity_3m"] for r in repo.sales(
        [c["product"]["product_id"] for c in qualified])}
    shortages=[]
    groups=search.data['unavailable']+[{'product_id':c['product']['product_id'],'product_name':c['product']['product_name'],
        'variants':c.get('unavailable_variants',[])} for c in candidates if c['product']['product_id'] not in {q['product']['product_id'] for q in qualified}]
    for group in groups:
        offers=[QuoteItem(sku=v['sku'],quantity=filters.quantity) for v in group['variants']]
        if not offers:continue
        prices=QuoteTool(repo).price_candidates(offers,filters.card_company,check_stock=False).data['prices']
        eligible=[v for v in prices if filters.budget is None or filters.budget.accepts(v['total'],filters.quantity)]
        if eligible:
            shortages.append({'product_id':group['product_id'],'product_name':group['product_name'],
                'reason':'OUT_OF_STOCK' if all(v['stock_quantity']==0 for v in eligible) else 'INSUFFICIENT_STOCK',
                'requested_quantity':filters.quantity,'available_quantity':max(v['stock_quantity'] for v in eligible)})
    return qualified, sales, shortages


async def recommend(engine, body, model_client=None):
    filters = body.filters
    candidates, sales, unavailable = await asyncio.to_thread(read_once_retry, engine,
        lambda repo: prepare_candidates(repo, filters))
    warnings = []
    if unavailable:
        warnings.append(f"조건에 해당하지만 품절 또는 요청 수량이 부족한 상품 {', '.join(p['product_name'] for p in unavailable)} {len(unavailable)}기종은 추천에서 제외했습니다.")
    if not candidates:
        return Response(request_id=body.request_id, status="NO_MATCH",
            message="현재 조건에 맞는 구매 가능한 상품이 없습니다. 예산·용량·수량 중 완화할 조건을 알려주세요.",
            data={"recommendations": [], "excluded_products":unavailable, 'applied_filters':filters.model_dump(exclude_none=True)}, warnings=warnings)
    client = model_client or OllamaClient()
    scores, hits = {}, []
    if filters.purpose:
        rag = await RagTool(engine, client).search_product_documents(filters.purpose,
            [c["product"]["product_id"] for c in candidates])
        hits = rag.data["hits"]
        scores = await client.evaluate(filters.purpose, candidates, hits)
    candidates.sort(key=lambda c: (-scores.get(c["product"]["product_id"], 0),
        -sales.get(c["product"]["product_id"], 0), c["representative"]["sale_price"],
        c["product"]["product_id"]))
    recommendations, sources = [], []
    for position, candidate in enumerate(candidates[:body.limit], 1):
        product, variant, price = candidate["product"], candidate["representative"], candidate["price"]
        reasons = [{"summary": purpose_reason(product, filters.purpose),
                    "basis": "SPEC", "source_ids": []}]
        for hit in (h for h in hits if h["product_id"] == product["product_id"]):
            source_id = f"source-{len(sources) + 1}"
            # 문서 내용을 새 성능 주장으로 바꾸지 않고 짧게 발췌해 근거로 제공한다.
            content = " ".join(hit["content"].split())
            match = re.search(r'카메라|촬영|OIS|줌', content, re.I) if filters.purpose and re.search(r'사진|카메라|촬영', filters.purpose) else None
            summary = content[max(0,match.start()-25):match.start()+155] if match else content[:180]
            sources.append({"source_id": source_id, "source_file": hit["metadata"]["source_file"],
                            "page_number": hit["metadata"]["page_number"], "summary": summary})
            reasons.append({"summary": "요청 용도와 관련해 검색된 설명서 근거입니다.",
                            "basis": "DOCUMENT", "source_ids": [source_id]})
        if filters.purpose and not any(r["basis"] == "DOCUMENT" for r in reasons):
            warnings.append(f"{product['product_name']}: 설명서 근거를 찾지 못해 등록 사양만 제공합니다.")
        if filters.purpose and scores.get(product["product_id"], 0) == 0:
            warnings.append(f"{product['product_name']}: 요청 용도 적합성을 판단할 근거가 충분하지 않습니다.")
        if price["promotion_status"] == "APPLIED":
            warnings.append(f"{product['product_name']}: {filters.card_company} 적용 시 {filters.quantity}대 {price['total']:,}원입니다.")
        public_variant = {k: variant[k] for k in ("sku", "product_id", "color", "ram_gb", "storage_gb",
                          "sale_price", "stock_quantity", "price_updated_at")} | {"availability": "AVAILABLE"}
        recommendations.append(product | {"position": position, "price_from": variant["sale_price"],
            "currency": "KRW", "representative_variant": public_variant, "reasons": reasons})
    message = f"조건을 충족하는 상품 {len(recommendations)}기종입니다. 표시 가격은 해당 옵션의 판매가입니다."
    if filters.purpose and re.search(r'사진|카메라|촬영', filters.purpose):
        message = f"사진 촬영용으로는 {recommendations[0]['product_name']}부터 검토해 보세요. 등록된 카메라 사양과 검색된 설명서 근거로 비교한 순서이며, 실제 촬영 품질을 보장하는 평가는 아닙니다."
        if scores.get(recommendations[0]['product_id'],0) == 0:
            message = '사진 촬영 적합성을 우선 추천할 근거가 충분하지 않습니다. 확인 가능한 카메라 사양을 비교해 드립니다.'
    return Response(request_id=body.request_id, status="OK", message=message,
        data={"recommendations": recommendations, "excluded_products":unavailable, 'applied_filters':filters.model_dump(exclude_none=True)}, sources=sources,
        evidence_status="FOUND" if sources else "NOT_FOUND" if filters.purpose else "NOT_USED",
        warnings=warnings)
