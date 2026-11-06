"""명시적인 상품·금액·옵션 요청의 해석과 모델 조건 변경의 근거 검사."""
import re

from backend.app.models import ChatAction, RecommendFilters


def normalize(text):
    text = text.lower().replace('갤럭시', 'galaxy').replace('레드미', 'redmi').replace('아이폰', 'iphone')
    text = text.replace('플러스', '+').replace('plus', '+').replace('울트라', 'ultra')
    return re.sub(r'[^a-z0-9+]', '', text)


def mentioned_products(message, catalogue):
    compact = normalize(message)
    matches = []
    for p in catalogue:
        name = normalize(p['product_name'])
        names = {name, name[:-2] if name.endswith('5g') else name}
        for candidate in names:
            index = compact.find(candidate)
            if index >= 0 and (index+len(candidate) == len(compact) or
                              not compact[index+len(candidate)].isdigit()):
                matches.append((index, index+len(candidate), p['product_id']))
        if re.search(r'(?<![A-Za-z0-9_-])'+re.escape(p['product_id'])+r'(?![A-Za-z0-9_-])', message, re.I):
            matches.append((-1, -1, p['product_id']))
    ids = []
    for start, end, pid in sorted(matches, key=lambda m: -(m[1]-m[0])):
        if start >= 0 and any(a <= start and b >= end and b-a > end-start for a,b,_ in matches):
            continue
        if pid not in ids:
            ids.append(pid)
    return ids


def budget_in(message):
    found = list(re.finditer(r'(\d[\d,]*(?:\.\d+)?)\s*(만\s*원|만원|원)', message))
    if not found:
        return None
    found = found[-1]
    from decimal import Decimal
    amount = int(Decimal(found[1].replace(',', '')) * (10000 if '만' in found[2] else 1))
    return amount if amount > 0 else None


BRANDS = {'samsung': ('samsung','삼성','갤럭시만'), 'xiaomi': ('xiaomi','샤오미','레드미만'),
          'apple': ('apple','애플','아이폰만')}


def budget_scope(message, default='PER_UNIT'):
    lines = [line for line in message.splitlines() if budget_in(line) is not None]
    clause = lines[-1] if lines else message
    return 'TOTAL' if re.search(r'총|합계|전체\s*(?:예산|금액|수량|구매|\d)', clause) else default


def supported_patch(updates, message):
    """형식이 맞더라도 입력 근거가 없는 모델 조건은 적용하지 않는다."""
    clean = {}
    lower = message.lower()
    for key, value in updates.items():
        if key == 'budget':
            amount = budget_in(message)
            if amount:
                clean[key] = {'amount': amount, 'scope': budget_scope(message, value.get('scope', 'PER_UNIT'))}
        elif key == 'brands':
            brands = [v for v in value if any(alias in lower for alias in BRANDS.get(v.lower(), (v.lower(),)))]
            if brands: clean[key] = brands
        elif key == 'purpose':
            # 내부 태그나 상품 설명에서 추론한 용도를 저장하지 않는다.
            if isinstance(value, str) and value.strip() in message: clean[key] = value.strip()
        elif key in ('colors', 'card_company'):
            if key == 'card_company' and isinstance(value, str) and value in message: clean[key] = value
            if key == 'colors' and value and all(v in message for v in value): clean[key] = value
        elif key == 'quantity':
            match = re.search(r'(\d+)\s*대', message)
            if match: clean[key] = int(match[1])
        elif key in ('ram_gb','storage_gb','min_storage_gb'):
            if re.search(r'(?<!\d)'+str(value)+r'\s*(?:GB|기가)', message, re.I): clean[key] = value
        elif key in ('min_display_inches','max_weight_g','min_battery_mah'):
            if str(value) in message: clean[key] = value
    return clean


def mentioned_positions(message):
    matches=[]
    for token, number in (('첫',1),('두',2),('세',3),('네',4),('다섯',5)):
        matches.extend((m.start(),number) for m in re.finditer(token+r'\s*번째',message))
    matches.extend((m.start(),int(m[1])) for m in re.finditer(r'(?<!\d)([1-5])\s*(?:번째|번)(?!\d)',message))
    return list(dict.fromkeys(n for _,n in sorted(matches)))


def explicit_action(message, state, catalogue):
    positions=mentioned_positions(message)
    if positions and '견적' in message:
        quantity=re.search(r'(\d+)\s*대(?!\s*당)',message)
        return ChatAction(intent='QUOTE',positions=positions,
                          updates={'quantity':int(quantity[1])} if quantity else {})
    if re.search(r'그\s*중|이\s*중|(?:직전|방금|추천).*목록.*중', message) and re.search(r'사진|촬영|카메라|배터리|게임|영상|가벼', message):
        return ChatAction(intent='RECOMMEND', within_latest=True, updates={'purpose':message})
    if re.search(r'판매\s*(?:량|순위|랭킹)|판매.*(?:순위|많)|많이\s*(?:팔|판매)|베스트셀러', message):
        updates = {}
        for name, aliases in BRANDS.items():
            if any(a in message.lower() for a in aliases):
                updates.setdefault('brands', []).append({'samsung':'Samsung','xiaomi':'Xiaomi','apple':'Apple'}[name])
        return ChatAction(intent='RANKING', updates=updates,
            within_latest=bool(re.search(r'그중|그 중|이 중|이중', message)))
    targets = mentioned_products(message, catalogue)
    if re.search(r'장점|단점|특징|설명|성능|어떤\s*점|좋은\s*점|어때', message) and '비교' not in message and '추천' not in message:
        if targets or state.get('selected_product_ids'):
            return ChatAction(intent='KNOWLEDGE',product_ids=targets)
    quantity = re.search(r'(\d+)\s*대(?!\s*당)', message)
    updates = {'quantity': int(quantity[1])} if quantity else {}
    weight=re.search(r'(\d+)\s*(?:g|그램)\s*(?:이하|이내)',message,re.I)
    display=re.search(r'(\d+(?:\.\d+)?)\s*인치\s*이상',message)
    battery=re.search(r'(\d[\d,]*)\s*(?:mAh|밀리암페어)\s*이상',message,re.I)
    if weight: updates['max_weight_g']=int(weight[1])
    if display: updates['min_display_inches']=float(display[1])
    if battery: updates['min_battery_mah']=int(battery[1].replace(',',''))
    amount = budget_in(message)
    if amount is not None and ('예산' in message or re.search(r'이하|이내|까지|미만', message)):
        scope = budget_scope(message, state.get('constraints', {}).get('budget', {}).get('scope', 'PER_UNIT'))
        updates['budget'] = {'amount': amount, 'scope': scope}
    has_quote = bool(re.search(r'견적|얼마|구매.*(?:원|금액)', message))
    if targets and re.search(r'색상|컬러|옵션|상세|재고|색.*있', message) and not has_quote:
        return ChatAction(intent='COMPARE' if '비교' in message else 'DETAILS', product_ids=targets, updates=updates)
    if targets and has_quote:
        return ChatAction(intent='QUOTE', product_ids=targets, updates=updates)
    if '견적' in message:
        return ChatAction(intent='QUOTE',updates=updates)
    if any(k in updates for k in ('budget','max_weight_g','min_display_inches','min_battery_mah')) and not targets and not has_quote:
        for name, aliases in BRANDS.items():
            if any(a in message.lower() for a in aliases):
                updates.setdefault('brands', []).append({'samsung':'Samsung','xiaomi':'Xiaomi','apple':'Apple'}[name])
        if re.search(r'배터리|사진|카메라|게임|영상|가벼|업무|통화', message):
            updates['purpose'] = message
        return ChatAction(intent='RECOMMEND', updates=updates)
    return None


def grounded_action(action, message):
    updates = supported_patch(action.updates, message)
    field_names = {'colors': r'색|컬러', 'brands': r'브랜드|제조사', 'budget': r'예산|가격',
                   'storage_gb':r'용량|저장', 'min_storage_gb':r'용량|저장', 'ram_gb':r'램|RAM',
                   'purpose':r'용도', 'card_company':r'카드'}
    clear = [f for f in action.clear_fields if re.search(r'상관없|아무|제한.*없|해제', message) and
             f in field_names and re.search(field_names[f], message, re.I)]
    return action.model_copy(update={'updates': updates, 'clear_fields': clear,
        'within_latest': bool(re.search(r'그중|그 중|이 중|이중|목록.*중', message))})
