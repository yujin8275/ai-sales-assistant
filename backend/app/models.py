"""첫 구현 범위: 직접 견적 API 및 상품 조회 Tool의 계약."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

MAX_MONEY = 9_007_199_254_740_991
Quantity = Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]
SKU = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuoteItem(InputModel):
    sku: SKU
    quantity: Quantity


class QuoteRequest(InputModel):
    request_id: UUID
    items: list[QuoteItem] = Field(min_length=1)
    card_company: Name | None = None


PositiveInt = Annotated[int, Field(strict=True, gt=0)]
ProductId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Budget(InputModel):
    amount: Annotated[int, Field(strict=True, gt=0, le=MAX_MONEY)]
    scope: Literal["PER_UNIT", "TOTAL"] = "PER_UNIT"
    comparison: Literal['LTE','LT','GTE','GT','RANGE'] = 'LTE'
    upper_amount: Annotated[int, Field(strict=True,gt=0,le=MAX_MONEY)] | None = None

    @model_validator(mode='after')
    def valid_range(self):
        if self.comparison=='RANGE' and (self.upper_amount is None or self.upper_amount<self.amount):
            raise ValueError('가격 범위를 확인하세요')
        if self.comparison!='RANGE' and self.upper_amount is not None:raise ValueError('범위에만 상한 허용')
        return self

    def accepts(self,total,quantity):
        factor=quantity if self.scope=='PER_UNIT' else 1
        bound=self.amount*factor
        return {'LTE':lambda:total<=bound,'LT':lambda:total<bound,
                'GTE':lambda:total>=bound,'GT':lambda:total>bound,
                'RANGE':lambda:bound<=total<=self.upper_amount*factor}[self.comparison]()



class ProductFilters(InputModel):
    brands: list[Name] = Field(default_factory=list)
    colors: list[Name] = Field(default_factory=list)
    quantity: Quantity = 1
    ram_gb: PositiveInt | None = None
    storage_gb: PositiveInt | None = None
    min_storage_gb: PositiveInt | None = None
    min_display_inches: Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)] | None = None
    max_weight_g: PositiveInt | None = None
    min_battery_mah: PositiveInt | None = None
    scope_product_ids: list[ProductId] | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null(cls, data):
        if isinstance(data, dict) and any(v is None for v in data.values()):
            raise ValueError("제한하지 않는 필드는 null 대신 생략하세요.")
        return data

    @model_validator(mode="after")
    def exclusive_storage(self):
        if self.storage_gb is not None and self.min_storage_gb is not None:
            raise ValueError("storage_gb와 min_storage_gb는 함께 지정할 수 없습니다.")
        return self


class RecommendFilters(ProductFilters):
    budget: Budget | None = None
    card_company: Name | None = None
    purpose: Text | None = None


class RecommendRequest(InputModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "request_id": "33333333-3333-4333-8333-333333333333",
        "filters": {"budget": {"amount": 500000, "scope": "PER_UNIT"}, "purpose": "배터리가 오래 가는 휴대폰"},
        "limit": 5}})
    request_id: UUID
    filters: RecommendFilters = Field(default_factory=RecommendFilters)
    limit: Annotated[int, Field(strict=True, ge=1, le=5)] = 5


class Suitability(InputModel):
    product_id: ProductId
    score: Annotated[int, Field(strict=True, ge=0, le=3)]


class SuitabilityResult(InputModel):
    evaluations: list[Suitability]


class ToolResult(BaseModel):
    status: str
    data: dict | None = None
    issues: list[dict] = Field(default_factory=list)


class Response(BaseModel):
    request_id: UUID
    session_id: UUID | None = None
    status: Literal["OK", "NEED_INPUT", "NO_MATCH", "NOT_FOUND", "OUT_OF_STOCK", "ERROR"]
    message: str
    data: dict | None = None
    questions: list[dict] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    evidence_status: Literal["FOUND", "NOT_FOUND", "NOT_USED"] = "NOT_USED"
    warnings: list[str] = Field(default_factory=list)
    error: dict | None = None
    follow_up: dict | None = None

    @model_validator(mode='after')
    def next_steps(self):
        if self.follow_up or self.questions or self.status in ('ERROR','NEED_INPUT'):return self
        data=self.data or {};options=[];text=''
        products=data.get('recommendations') or data.get('sales_ranking') or []
        if self.status=='NO_MATCH':
            text='예산·브랜드·용량·수량 중 어떤 조건을 조정할 수 있을까요? 동의한 조건만 변경해 다시 찾겠습니다.'
        elif self.status=='OUT_OF_STOCK':
            text='구매 수량을 줄이거나 다른 색상·용량의 재고를 확인할 수 있습니다. 어떤 쪽을 원하시나요?'
        elif products:
            purpose=data.get('applied_filters',{}).get('purpose')
            text='주로 사진 촬영·게임·배터리 중 무엇이 중요한가요? 그 기준으로 다시 추천할 수 있습니다.' if not purpose else '후보를 비교하거나 원하는 제품의 옵션을 확인해 보세요.'
            if len(products)>1:
                a,b=products[:2];options.append({'label':'상위 두 제품 비교','message':a['product_name']+'와 '+b['product_name']+' 비교해줘'})
            options.append({'label':'첫 제품 옵션 확인','message':products[0]['product_name']+'의 전체 옵션과 재고를 보여줘'})
        elif data.get('quote'):
            text='수량을 변경해 재계산할 수 있습니다.' if any(i.get('promotion_status')=='APPLIED' for i in data['quote']['items']) else '사용할 카드사를 알려주시면 할인 적용 여부를 확인할 수 있습니다. 수량 변경도 가능합니다.'
        elif data.get('variants'):
            text='원하는 색상·RAM·저장 용량의 옵션을 고르고 구매 수량을 알려주시면 견적을 계산하겠습니다.'
        elif data.get('comparison'):
            text='마음에 드는 제품을 알려주시면 옵션과 재고를 확인해 드리겠습니다.'
        elif data.get('product'):
            name=data['product']['product_name'];text='구매 옵션과 가격·재고도 확인할 수 있습니다.'
            options=[{'label':'옵션 확인','message':name+'의 전체 옵션과 재고를 보여줘'}]
        if text:self.follow_up={'text':text,'options':options}
        return self



class SessionCreate(InputModel):
    pass


class ResetRequest(InputModel):
    request_id: UUID


class ChatRequest(InputModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "session_id": "11111111-1111-4111-8111-111111111111",
        "request_id": "22222222-2222-4222-8222-222222222222", "message": "50만원 이하 휴대폰 추천해줘"}})
    session_id: UUID
    request_id: UUID
    message: Text


class SelectedItem(InputModel):
    sku: SKU
    quantity: Quantity | None = None


class ChatAction(InputModel):
    intent: Literal["RECOMMEND", "DETAILS", "KNOWLEDGE", "STOCK", "COMPARE", "RANKING", "QUOTE", "UNKNOWN"]
    updates: dict = Field(default_factory=dict)
    clear_fields: list[str] = Field(default_factory=list)
    product_ids: list[ProductId] = Field(default_factory=list)
    positions: list[Annotated[int, Field(strict=True, ge=1, le=5)]] = Field(default_factory=list)
    items: list[SelectedItem] = Field(default_factory=list)
    search_product_ids: list[ProductId] | None = None
    within_latest: bool = False
    ambiguous_reference: bool = False
    criteria: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_patch(self):
        RecommendFilters.model_validate(self.updates)
        if any(k not in RecommendFilters.model_fields for k in self.clear_fields):
            raise ValueError("알 수 없는 조건 해제")
        return self
