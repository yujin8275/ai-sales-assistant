from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from backend.app.models import MAX_MONEY, QuoteItem, ToolResult


class BusinessError(Exception):
    def __init__(self, code, message, http_status=500):
        self.code, self.message, self.http_status = code, message, http_status
        super().__init__(message)


def money(value):
    if not 0 <= value <= MAX_MONEY:
        raise BusinessError("INVALID_INPUT", "금액이 지원 범위를 벗어났습니다.", 422)
    return int(value)


class ProductTool:
    def __init__(self, repository):
        self.repo = repository

    def search_products(self, filters):
        groups = {}
        for row in self.repo.search_variants(filters):
            require_price(row)
            groups.setdefault(row["product_id"], []).append(row)
        candidates, unavailable = [], []
        for product_id, variants in groups.items():
            available = [r for r in variants if r["stock_quantity"] >= filters.quantity]
            if not available:
                unavailable.append({"product_id": product_id, "product_name": self.repo.product(product_id)["product_name"], "variants": variants,
                    "reason": "OUT_OF_STOCK" if all(r["stock_quantity"] == 0 for r in variants)
                    else "INSUFFICIENT_STOCK"})
            else:
                candidates.append({"product": self.repo.product(product_id), "variants": available,"unavailable_variants":[r for r in variants if r not in available]})
        return ToolResult(status="OK", data={"candidates": candidates, "unavailable": unavailable})

    def compare_products(self, product_ids, criteria):
        if len(set(product_ids)) < 2:
            raise BusinessError("INVALID_INPUT", "비교할 상품을 두 개 이상 선택하세요.", 422)
        products = [self.repo.product(pid) for pid in dict.fromkeys(product_ids)]
        if any(p is None for p in products):
            return ToolResult(status="NOT_FOUND")
        differences = []
        supported = {"processor", "weight_g", "battery_mah", "display_inches", "cameras"}
        for field in criteria:
            if field in supported:
                differences.append(field + ": " + "; ".join(
                    f"{p['product_name']}={p['specs'].get(field)}" for p in products))
        for p in products:
            options = self.repo.product_variants(p["product_id"])
            storage = sorted({v["storage_gb"] for v in options if v["storage_gb"] is not None})
            differences.append(f"{p['product_name']} 저장 용량 옵션: {storage} GB")
        return ToolResult(status="OK", data={"comparison": {"products": products,
            "criteria": criteria, "differences": differences}})

    def get_sales_ranking(self, filters, limit=5):
        if type(limit) is not int or not 1 <= limit <= 5:
            raise BusinessError("INVALID_INPUT", "순위 개수는 1~5개입니다.", 422)
        return self._rank_products(filters, limit)

    def home_ranking(self):
        from backend.app.models import ProductFilters
        return self._rank_products(ProductFilters(), 8)

    def _rank_products(self, filters, limit):
        rows = self.repo.search_variants(filters)
        availability = {}
        for row in rows:
            require_price(row)
            availability[row["product_id"]] = availability.get(row["product_id"], False) or row["stock_quantity"] > 0
        sales = self.repo.sales(list(availability))
        if any(r.get('reference_date_count', 1) > 1 for r in sales) or len({r['sales_reference_date'] for r in sales if r['sales_reference_date']}) > 1:
            raise BusinessError('SALES_DATA_ERROR', '판매량 집계 기준일이 서로 달라 순위를 비교할 수 없습니다.')
        sales = [r for r in sales if r["sales_reference_date"] is not None]
        sales.sort(key=lambda r: (-r["sales_quantity_3m"], r["product_id"]))
        ranking = []
        for position, row in enumerate(sales[:limit], 1):
            variants = [v for v in rows if v['product_id'] == row['product_id']]
            purchasable = [v for v in variants if v['stock_quantity'] >= filters.quantity]
            representative = min(purchasable or variants, key=lambda v:(v['sale_price'], v['sku']))
            variant = {k:representative[k] for k in ('sku','product_id','color','ram_gb','storage_gb',
                       'sale_price','stock_quantity','price_updated_at')}
            variant['availability'] = 'AVAILABLE' if purchasable else 'OUT_OF_STOCK' if not any(v['stock_quantity'] for v in variants) else 'INSUFFICIENT_STOCK'
            ranking.append(self.repo.product(row['product_id']) | {
                'position':position,'rank':position,'sales_quantity_3m':row['sales_quantity_3m'],
                'sales_reference_date':row['sales_reference_date'],
                'availability':variant['availability'], 'representative_variant':variant,
                'price_from':representative['sale_price'], 'currency':'KRW',
                'reasons':[{'summary':'최근 3개월 SKU별 판매량을 기종 단위로 합산했습니다.','basis':'SPEC','source_ids':[]}]})
        return ToolResult(status='OK', data={'sales_ranking':ranking})

    def get_product_details(self, product_id, storage_gb=None, color=None,
                            ram_gb=None, requested_quantity=None):
        product = self.repo.product(product_id)
        if product is None:
            return ToolResult(status="NOT_FOUND")
        variants = []
        for row in self.repo.product_variants(product_id):
            if any(value is not None and row[key] != value for key, value in
                   (("storage_gb", storage_gb), ("color", color), ("ram_gb", ram_gb))):
                continue
            require_price(row)
            variants.append({key: row[key] for key in
                ("sku", "product_id", "color", "ram_gb", "storage_gb", "sale_price",
                 "stock_quantity", "price_updated_at")} | {
                    "availability": "OUT_OF_STOCK" if row["stock_quantity"] == 0 else
                    "INSUFFICIENT_STOCK" if requested_quantity is not None and
                    row["stock_quantity"] < requested_quantity else "AVAILABLE"})
        return ToolResult(status="OK", data={"product": product, "variants": variants})


def require_price(row):
    if any(row.get(k) is None for k in ("sale_price", "stock_quantity", "price_updated_at")):
        raise BusinessError("PRICE_CONFIG_ERROR", "상품 가격·재고 정보 확인이 필요합니다.")
    money(row["sale_price"])


class QuoteTool:
    def __init__(self, repository, now=None):
        self.repo = repository
        self.now = now or datetime.now(ZoneInfo("Asia/Seoul"))

    def _policy(self, company):
        if company is None:
            return None
        policies = self.repo.promotions(company)
        if len(policies) > 1:
            raise BusinessError("PROMO_CONFIG_ERROR", "카드 할인 정책 확인이 필요합니다.")
        return policies[0] if policies else None

    def _price(self, row, quantity, company, policy):
        require_price(row)
        rate, promotion_id = Decimal("0.00"), None
        status = "NOT_REQUESTED" if company is None else "NOT_FOUND"
        if policy is not None:
            today = self.now.astimezone(ZoneInfo("Asia/Seoul")).date()
            if not policy["is_active"] or today < policy["start_date"]:
                status = "INACTIVE"
            elif today > policy["end_date"]:
                status = "EXPIRED"
            elif not policy["applies_to_all"] and row["product_id"] not in policy["product_ids"]:
                status = "NOT_ELIGIBLE"
            else:
                status = "APPLIED"
                rate = Decimal(str(policy["discount_rate"]))
                promotion_id = policy["promotion_id"]
        subtotal = money(row["sale_price"] * quantity)
        discount = money(int((Decimal(subtotal) * rate / 100).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)))
        return {"sku": row["sku"], "quantity": quantity, "unit_price": row["sale_price"],
                "subtotal": subtotal, "discount_rate": f"{rate:.2f}",
                "discount_amount": discount, "total": money(subtotal - discount),
                "promotion_id": promotion_id, "promotion_status": status,
                "stock_quantity": row["stock_quantity"],
                "price_updated_at": row["price_updated_at"]}

    def _load(self, items):
        rows = {r["sku"]: r for r in self.repo.variants([i.sku for i in items])}
        missing, stock = [], []
        for item in items:
            row = rows.get(item.sku)
            if row is None:
                missing.append(item.sku)
                continue
            require_price(row)
            if row["stock_quantity"] < item.quantity:
                stock.append({"sku": item.sku, "requested_quantity": item.quantity,
                              "available_quantity": row["stock_quantity"],
                              "shortage_quantity": item.quantity - row["stock_quantity"]})
        return rows, missing, stock

    def calculate_quote(self, items, card_company=None):
        quantities = defaultdict(int)
        for item in items:
            quantities[item.sku] += item.quantity
            if quantities[item.sku] > 2_147_483_647:
                raise BusinessError("INVALID_INPUT", "합산 수량이 지원 범위를 벗어났습니다.", 422)
        merged = [QuoteItem(sku=sku, quantity=qty) for sku, qty in quantities.items()]
        rows, missing, stock = self._load(merged)
        if missing or stock:
            data = {}
            if missing:
                data["missing_skus"] = missing
            if stock:
                data["stock_issues"] = stock
            return ToolResult(status="NOT_FOUND" if missing else "OUT_OF_STOCK", data=data)
        policy = self._policy(card_company)
        lines = []
        for item in merged:
            row = rows[item.sku]
            lines.append(self._price(row, item.quantity, card_company, policy) | {
                key: row[key] for key in ("product_id", "product_name", "color", "ram_gb", "storage_gb")})
        subtotal = money(sum(line["subtotal"] for line in lines))
        discount = money(sum(line["discount_amount"] for line in lines))
        return ToolResult(status="OK", data={"quote": {
            "currency": "KRW", "items": lines, "subtotal": subtotal,
            "discount_amount": discount, "total": money(subtotal - discount),
            "checked_at": self.now}})

    def price_candidates(self, offers, card_company=None, check_stock=True):
        rows, missing, stock = self._load(offers)
        policy = self._policy(card_company)
        excluded = set(missing) | ({i["sku"] for i in stock} if check_stock else set())
        prices = [self._price(rows[i.sku], i.quantity, card_company, policy)
                  for i in offers if i.sku not in excluded]
        issues = [{"code": "NOT_FOUND", "sku": sku} for sku in missing]
        issues += [{"code": "OUT_OF_STOCK", "sku": i["sku"], "details": i} for i in stock]
        return ToolResult(status="OK", data={"prices": prices}, issues=issues)

