# ABC Electronics API 및 Tool 입출력 명세서

버전: 0.2 초안  
작성일: 2026-11-05  
기준: 기능요구사항 0.3·기술 결정 0.3·API 선택 A01~A07 및 명세 간소화 검토  
상태: 구현할 계약을 정의한다. 실제 API·Tool 구현과 동작 평가는 아직 수행하지 않았다.

## 1. 범위와 유지할 원칙

API 6개와 Product·RAG·Quote Tool 3개를 유지한다. 채팅의 상품·SKU·수량 선택은 message 문장으로 받는다. 직접 /recommend·/quote는 상담 상태를 변경하지 않는다. 추천은 최대 5기종이며 대표 SKU와 최저 판매가를 함께 표시한다. 금액은 원 단위 정수·KRW다. 문서 근거는 문서명·페이지·요약으로 제공한다.

SSE는 진행·완료·오류 전달에 사용한다. 첫 버전에는 끊긴 스트림의 자동 복구·이벤트 재생·서버 재시작 후 작업 재개를 구현하지 않는다. 요청 중복 방지와 완료 결과 재사용은 유지한다.

상세 실행 흐름·세션 순서·초기화 절차는 [④ Agent 대화 흐름·상태 설계](ABC_Electronics_Agent_대화흐름_상태설계_v0.1.md), 재시도·오류 안내는 [⑤ 예외 처리 명세](ABC_Electronics_예외처리명세_v0.1.md)로 분리했다. 이 문서는 입력·출력·검증 조건과 책임 경계를 정의한다.

## 2. API와 공통 자료형

| API | 본문 | 응답 | 상태 변경 |
|---|---|---|---|
| POST /sessions | {} | 201, SessionData | 세션 생성 |
| POST /chat | ChatRequest | 200, SSE | 정상 업무 결과를 상담에 반영 |
| POST /recommend | RecommendRequest | 200, 공통 응답 | 없음 |
| POST /quote | QuoteRequest | 200, 공통 응답 | 없음 |
| POST /sessions/{session_id}/reset | ResetRequest | 200, SessionData | 이전 상담 종료·새 ID 발급 |
| GET /health | 없음 | 준비 200 / 필수 연결 실패 503, HealthData | 없음 |

객체의 정의하지 않은 입력 필드는 거부한다. 정수에는 bool·소수를 허용하지 않는다. 문자열 식별자는 DB 존재 여부를 확인한다. datetime은 시간대가 포함된 ISO 8601 UTC 문자열, 사용자 표시는 한국 시간이다. 카드 기간 판정에는 서버의 Asia/Seoul 날짜를 사용한다.

| 별칭 | 정의 |
|---|---|
| UUID | UUID 문자열. session_id·list_id는 서버 발급, request_id는 새 요청마다 클라이언트가 생성 |
| Money | 0 이상 9,007,199,254,740,991 이하 원 단위 정수. 음수·부동소수 금액을 반환하지 않음 |
| Quantity | 1~2,147,483,647의 정수. 중복 SKU 합산 수량도 같은 범위에서 검증 |
| ProductId / SKU | 비어 있지 않은 문자열, 최대 40 / 64자 |
| GB | 양의 정수. 1TB=1024GB, 2TB=2048GB |
| DecimalRate | 퍼센트 단위 십진 문자열, 예: "5.00". Python 내부 계산은 Decimal |

## 3. 요청 계약

### 3.1 세션·채팅·직접 API
| 필드 | 자료형 | 필수 | 생략 시 기본값 | null 허용·검증 |
|---|---|---|---|---|
| ChatRequest.session_id | UUID | 예 | 없음 | 불가; 미등록 404·만료 410 |
| ChatRequest.request_id | UUID | 예 | 없음 | 불가; 동일 ID·다른 입력은 409 |
| ChatRequest.message | string | 예 | 없음 | 불가; 공백만 있는 문장 거부 |
| RecommendRequest.request_id | UUID | 예 | 없음 | 불가 |
| RecommendRequest.filters | RecommendFilters | 아니오 | {} | 불가 |
| RecommendRequest.limit | integer | 아니오 | 5 | 불가; 1~5 |
| QuoteRequest.request_id | UUID | 예 | 없음 | 불가 |
| QuoteRequest.items | QuoteItem[] | 예 | 없음 | 불가; 최소 1개 |
| QuoteRequest.card_company | string | 아니오 | null | 허용; 빈 문자열 거부 |
| QuoteItem.sku | SKU | 예 | 없음 | 불가 |
| QuoteItem.quantity | Quantity | 예 | 없음 | 불가 |
| ResetRequest.request_id | UUID | 예 | 없음 | 불가 |

POST /sessions는 빈 객체만 받는다. reset의 기존 ID는 URL에 포함한다. 직접 API는 session_id를 입력받지 않는다. 선택지 클릭도 options.message를 /chat.message로 보낸다. /chat에 selected_sku·selected_items 필드를 추가하지 않는다.

#### 채팅 요청 예시
```json
{
  "session_id": "11111111-1111-4111-8111-111111111111",
  "request_id": "22222222-2222-4222-8222-222222222222",
  "message": "두 번째 제품으로 3대 견적 내줘"
}
```

#### 직접 추천 요청 예시
```json
{
  "request_id": "33333333-3333-4333-8333-333333333333",
  "filters": {
    "brands": [
      "Xiaomi"
    ],
    "budget": {
      "amount": 300000,
      "scope": "PER_UNIT"
    },
    "quantity": 3,
    "storage_gb": 128,
    "scope_product_ids": [
      "RM-15C"
    ]
  },
  "limit": 5
}
```

#### 직접 견적 요청 예시
```json
{
  "request_id": "44444444-4444-4444-8444-444444444444",
  "items": [
    {
      "sku": "RM-15C-BK-4-128",
      "quantity": 3
    }
  ],
  "card_company": null
}
```

### 3.2 RecommendFilters

선택 필드는 아래 표대로 생략한다. null을 제한 없음의 별도 표현으로 혼용하지 않는다. 브랜드·색상·카드사의 일상 표현을 정규화하고, 해석이 모호하면 확인한다.
| 필드 | 자료형 | 필수 | 생략 시 기본값 | null 허용·검증 |
|---|---|---|---|---|
| brands, colors | string[] | 아니오 | [] | 불가; 각 원소는 비어 있지 않은 문자열, []는 제한 없음 |
| budget | Budget | 아니오 | 필드 생략 | 불가; 생략하면 예산 제한 없음 |
| budget.amount | Money | budget가 있으면 예 | 없음 | 불가; 0보다 큼 |
| budget.scope | PER_UNIT 또는 TOTAL | 아니오 | PER_UNIT | 불가 |
| quantity | Quantity | 아니오 | 1 | 불가; 검색 기준 기본값이며 고객의 견적 수량 확정으로 간주하지 않음 |
| ram_gb, storage_gb | GB | 아니오 | 필드 생략 | 불가; 해당 필터 없음 |
| min_storage_gb | GB | 아니오 | 필드 생략 | 불가; storage_gb와 동시 입력 거부 |
| min_display_inches | number | 아니오 | 필드 생략 | 불가; 유한한 양수 |
| max_weight_g, min_battery_mah | integer | 아니오 | 필드 생략 | 불가; 양수 |
| purpose | string | 아니오 | 필드 생략 | 불가; 공백만 있는 문장 거부 |
| card_company | string | 아니오 | 필드 생략 | 불가; 카드 없음은 생략으로 표현 |
| scope_product_ids | ProductId[] | 아니오 | 필드 생략 | 불가; 생략은 전체 범위, []는 빈 범위이므로 NO_MATCH |

scope_product_ids는 filters 안에서만 정의한다. Product Tool에도 별도 중복 인자로 전달하지 않는다. “직전 목록 중에서”는 서버가 저장한 ID들로 이 필드를 채운다. 제한 범위가 비어 있을 때 전체 상품 검색으로 풀지 않는다.

## 4. 응답 계약

### 4.1 공통 응답
| 필드 | 자료형 | 필수 | 생략 시 기본값 | null 허용·검증 |
|---|---|---|---|---|
| request_id | UUID | 예 | 없음 | 불가; /sessions·/health는 서버 생성 |
| session_id | UUID | 예 | 없음 | 직접 API·health·세션 없는 오류는 null |
| status | 업무 상태 enum | 예 | 없음 | 불가 |
| message | string | 예 | 없음 | 불가; 사용자 안내 |
| data | 응답 데이터 객체 | 예 | 없음 | ERROR·단순 결과 없음에서는 null 허용 |
| questions | Question[] | 예 | [] | 불가 |
| sources | Source[] | 예 | [] | 불가 |
| evidence_status | FOUND / NOT_FOUND / NOT_USED | 예 | NOT_USED | 불가 |
| warnings | string[] | 예 | [] | 불가 |
| error | ErrorData | 예 | null | ERROR에서 필수 객체, 그 외 null |

업무 상태는 OK, NEED_INPUT, NO_MATCH, NOT_FOUND, OUT_OF_STOCK, ERROR다. NEED_INPUT에는 questions가 한 개 이상 필요하다. OUT_OF_STOCK에는 부족 품목을 data.stock_issues에 담고 quote는 넣지 않는다. NO_MATCH는 data=null 또는 빈 recommendations로 표현하며 sources=[]다. 필요한 객체만 data 안에 포함하고 사용하지 않는 data 하위 키는 생략한다.

### 4.2 데이터 객체

아래 반환 필드는 별도 생략 표시가 없으면 필수이며 기본값은 없다. nullable이라고 명시한 필드는 키를 유지하고 미확인 시 null로 반환한다. 목록은 결과가 없으면 []다.
| 객체 | 필드와 자료형 |
|---|---|
| SessionData | session_id: UUID, expires_at: datetime |
| HealthData | ready: boolean, dependencies: {database: boolean, model: boolean} |
| Recommendation | position: integer(1~5), product_id: ProductId, product_name: string, brand: string, image_url: string nullable, price_from: Money, currency: KRW, representative_variant: Variant, specs: Specs, reasons: Reason[] |
| Product | product_id: ProductId, product_name: string, brand: string, image_url: string nullable, specs: Specs |
| Variant | sku: SKU, product_id: ProductId, color: string nullable, ram_gb: GB nullable, storage_gb: GB nullable, sale_price: Money, stock_quantity: integer>=0, price_updated_at: datetime, availability: AVAILABLE / OUT_OF_STOCK / INSUFFICIENT_STOCK |
| Specs | processor: string nullable, weight_g: integer nullable, battery_mah: integer nullable, display_inches: number nullable, cameras: Camera[] |
| Camera | camera_type: string nullable, resolution_mp: number nullable, aperture: string nullable, max_zoom: number nullable, ois: boolean nullable |
| Reason | summary: string, basis: SPEC / DOCUMENT, source_ids: string[]. DOCUMENT는 실존 Source ID를 1개 이상 참조 |
| Source 공개형 | source_id: string, source_file: string, page_number: integer>=1, summary: string |
| Question | question_id: string, text: string, missing_fields: string[](1개 이상), options: Option[], allow_free_text: boolean(항상 true) |
| Option | label: string, message: string. message는 선택 시 전송할 실제 채팅 문장 |
| ErrorData | code: 오류 코드 string, retryable: boolean |
| StockIssue | sku: SKU, requested_quantity: Quantity, available_quantity: integer>=0, shortage_quantity: Quantity |
| SalesRankRow | product_id: ProductId, rank: integer>=1, sales_quantity_3m: integer>=0, sales_reference_date: date, availability: AVAILABLE / OUT_OF_STOCK |
| Comparison | products: Product[](최소 2개), criteria: string[], differences: string[]. 용량 차이 포함 |

data의 지원 키는 session, health, recommendations, product, variants, comparison, sales_ranking, quote, missing_skus, stock_issues다. 각 키의 값은 해당 객체 또는 배열이다. 세션 생성·reset은 data.session, health는 data.health를 사용한다. 필수 연결이 준비되지 않은 /health는 503과 status=ERROR로 반환하고 data.health에 점검 결과를 남길 수 있다. 그 외 처리 오류의 data는 null이다.

최대 5개는 기종 수다. 전체 옵션은 선택 후 data.variants에서 반환하며, 색상·RAM·용량별 SKU를 합치지 않는다. price_from은 조건과 요청 수량을 충족하는 실제 대표 SKU의 판매가와 일치해야 한다. image_url은 backend에서 접근 가능한 이미지 경로이며 없으면 null이다. 사양 미확인은 null이며 0·false로 바꾸지 않는다.

Source의 document_id·chunk_id·product_id는 내부 검색 결과에서만 관리한다. 공개 출처 연결은 Reason.source_ids로 통일한다. SQL 조회에 임의 PDF 출처를 붙이지 않는다. PDF 링크·청크 원문은 공개하지 않는다.

### 4.3 견적 객체
| 객체 | 필드와 자료형·기본값 |
|---|---|
| Quote | currency: KRW, items: QuoteLine[](1개 이상), subtotal: Money, discount_amount: Money, total: Money, checked_at: datetime. 모두 필수·null 불가 |
| QuoteLine | sku·product_id·product_name: string, color: string nullable, ram_gb·storage_gb: GB nullable, quantity: Quantity, unit_price·subtotal·discount_amount·total: Money, stock_quantity: integer>=0, price_updated_at: datetime, discount_rate: DecimalRate, promotion_id: string nullable, promotion_status: enum. 모두 키 필수 |
| promotion_status | NOT_REQUESTED / APPLIED / NOT_FOUND / INACTIVE / EXPIRED / NOT_ELIGIBLE. 할인 미적용 시 rate="0.00", discount_amount=0 |

순수 직접 /quote는 생성 LLM 없이 검증된 계산값으로 정상 안내 문장을 만든다. 생성 LLM 실패 후 대체 문장을 만드는 기능은 두지 않는다. 재고 부족·미등록 품목이 있으면 정상 quote를 반환하지 않는다. 견적은 재고 예약·결제가 아니다.

## 5. 완전한 응답 JSON 예시

수치·상품·시각은 명세 확인용 예시이며 현재 응답을 보장하지 않는다. 추천 예시는 가격·재고 근거만 사용해 문서 검색을 하지 않은 경우다. Specs의 null은 미확인 값의 형식 예시다. 세션이 없는 직접 API의 session_id는 null이다.

### 5.1 추천 응답
```json
{
  "request_id": "33333333-3333-4333-8333-333333333333",
  "session_id": null,
  "status": "OK",
  "message": "조건을 충족하는 상품 1개입니다. 223,000원부터이며 해당 옵션은 RAM 4GB·128GB·미드나잇 블랙입니다.",
  "data": {
    "recommendations": [
      {
        "position": 1,
        "product_id": "RM-15C",
        "product_name": "Redmi 15C 5G",
        "brand": "Xiaomi",
        "image_url": null,
        "specs": {
          "processor": null,
          "weight_g": null,
          "battery_mah": null,
          "display_inches": null,
          "cameras": []
        },
        "price_from": 223000,
        "currency": "KRW",
        "representative_variant": {
          "sku": "RM-15C-BK-4-128",
          "product_id": "RM-15C",
          "color": "미드나잇 블랙",
          "ram_gb": 4,
          "storage_gb": 128,
          "sale_price": 223000,
          "stock_quantity": 13,
          "price_updated_at": "2026-11-04T06:00:00Z",
          "availability": "AVAILABLE"
        },
        "reasons": [
          {
            "summary": "등록 판매가와 재고가 요청 조건을 충족합니다.",
            "basis": "SPEC",
            "source_ids": []
          }
        ]
      }
    ]
  },
  "questions": [],
  "sources": [],
  "evidence_status": "NOT_USED",
  "warnings": [],
  "error": null
}
```

### 5.2 옵션 추가 질문 응답
```json
{
  "request_id": "22222222-2222-4222-8222-222222222222",
  "session_id": "11111111-1111-4111-8111-111111111111",
  "status": "NEED_INPUT",
  "message": "구매할 RAM 옵션을 선택해 주세요.",
  "data": {
    "product": {
      "product_id": "RM-15C",
      "product_name": "Redmi 15C 5G",
      "brand": "Xiaomi",
      "image_url": null,
      "specs": {
        "processor": null,
        "weight_g": null,
        "battery_mah": null,
        "display_inches": null,
        "cameras": []
      }
    },
    "variants": [
      {
        "sku": "RM-15C-BK-4-128",
        "product_id": "RM-15C",
        "color": "미드나잇 블랙",
        "ram_gb": 4,
        "storage_gb": 128,
        "sale_price": 223000,
        "stock_quantity": 13,
        "price_updated_at": "2026-11-04T06:00:00Z",
        "availability": "AVAILABLE"
      },
      {
        "sku": "RM-15C-BK-6-128",
        "product_id": "RM-15C",
        "color": "미드나잇 블랙",
        "ram_gb": 6,
        "storage_gb": 128,
        "sale_price": 232000,
        "stock_quantity": 13,
        "price_updated_at": "2026-11-04T06:00:00Z",
        "availability": "AVAILABLE"
      },
      {
        "sku": "RM-15C-BK-8-128",
        "product_id": "RM-15C",
        "color": "미드나잇 블랙",
        "ram_gb": 8,
        "storage_gb": 128,
        "sale_price": 242000,
        "stock_quantity": 12,
        "price_updated_at": "2026-11-04T06:00:00Z",
        "availability": "AVAILABLE"
      }
    ]
  },
  "questions": [
    {
      "question_id": "variant-selection",
      "text": "구매할 RAM 옵션을 선택해 주세요.",
      "missing_fields": [
        "sku"
      ],
      "options": [
        {
          "label": "RAM 4GB · 128GB · 미드나잇 블랙",
          "message": "RM-15C-BK-4-128로 3대 견적 내줘"
        },
        {
          "label": "RAM 6GB · 128GB · 미드나잇 블랙",
          "message": "RM-15C-BK-6-128로 3대 견적 내줘"
        },
        {
          "label": "RAM 8GB · 128GB · 미드나잇 블랙",
          "message": "RM-15C-BK-8-128로 3대 견적 내줘"
        }
      ],
      "allow_free_text": true
    }
  ],
  "sources": [],
  "evidence_status": "NOT_USED",
  "warnings": [],
  "error": null
}
```

### 5.3 견적 응답
```json
{
  "request_id": "44444444-4444-4444-8444-444444444444",
  "session_id": null,
  "status": "OK",
  "message": "요청하신 3대의 견적입니다.",
  "data": {
    "quote": {
      "currency": "KRW",
      "items": [
        {
          "sku": "RM-15C-BK-4-128",
          "product_id": "RM-15C",
          "product_name": "Redmi 15C 5G",
          "color": "미드나잇 블랙",
          "ram_gb": 4,
          "storage_gb": 128,
          "quantity": 3,
          "unit_price": 223000,
          "stock_quantity": 13,
          "price_updated_at": "2026-11-04T06:00:00Z",
          "subtotal": 669000,
          "discount_rate": "0.00",
          "discount_amount": 0,
          "total": 669000,
          "promotion_id": null,
          "promotion_status": "NOT_REQUESTED"
        }
      ],
      "subtotal": 669000,
      "discount_amount": 0,
      "total": 669000,
      "checked_at": "2026-11-05T05:00:00Z"
    }
  },
  "questions": [],
  "sources": [],
  "evidence_status": "NOT_USED",
  "warnings": [],
  "error": null
}
```

### 5.4 오류 응답
```json
{
  "request_id": "22222222-2222-4222-8222-222222222222",
  "session_id": "11111111-1111-4111-8111-111111111111",
  "status": "ERROR",
  "message": "응답 생성에 실패했습니다. 다시 요청해 주세요.",
  "data": null,
  "questions": [],
  "sources": [],
  "evidence_status": "NOT_USED",
  "warnings": [],
  "error": {
    "code": "MODEL_ERROR",
    "retryable": true
  }
}
```

## 6. SSE와 오류의 입출력

POST /chat은 JSON 요청에 text/event-stream을 반환한다. progress는 {request_id: UUID, stage: enum, message: string}이고 세 필드 모두 필수·null 불가다. stage는 QUEUED, ANALYZING, CHECKING_INPUT, SEARCHING_PRODUCTS, SEARCHING_DOCUMENTS, CALCULATING_QUOTE, GENERATING_RESPONSE, VALIDATING_RESPONSE다.

| event | data | 종료 여부 |
|---|---|---|
| progress | 진행 객체 | 계속 |
| final | 공통 응답. OK·NEED_INPUT·NO_MATCH·NOT_FOUND·OUT_OF_STOCK | 종료 |
| error | 공통 응답. status=ERROR | 종료 |

final과 error는 한 요청에서 둘 중 하나만 반환한다. 검증 전 금액·생성 문장을 전송하지 않는다. 시작 전 입력 오류는 HTTP 4xx, 의존 서비스·서버 오류는 HTTP 5xx다. 시작 후에는 HTTP 상태를 바꾸지 않고 error 이벤트로 전달한다. 재연결·순서·초기화 절차는 ④, 코드별 처리·재시도는 ⑤를 참조한다. 요청 제한 120초와 중복 처리 방지는 유지한다.

## 7. Tool 계약과 책임 경계

Tool은 LangGraph의 고정 단계에서 호출하는 Python 내부 서비스다. ToolResult={status: string, data: 객체 또는 null, issues: Issue[]}이며 세 키 모두 필수, issues 기본값은 []다. Issue는 code: string이 필수이고 field·sku·message는 생략 가능한 문자열, details는 생략 시 {}인 객체다. Tool은 최종 고객 문장을 작성하지 않는다.

### 7.1 Product Tool

| 함수 | 입력 | 출력 |
|---|---|---|
| search_products(filters) | ProductFilters | 후보 상품·SKU·품절/수량 부족 후보 |
| get_product_details(product_id, storage_gb?, color?, ram_gb?, requested_quantity?) | product_id 필수. 나머지 생략 시 제한 없음, null 입력 불가 | product: Product, variants: Variant[] |
| compare_products(product_ids, criteria) | ProductId[] 최소 2개, criteria: string[] 필수 | comparison: Comparison |
| get_sales_ranking(filters, limit=5) | ProductFilters, limit: integer(1~5) | sales_ranking: SalesRankRow[] |

ProductFilters는 RecommendFilters에서 budget·card_company·purpose를 제외한 조건이다. 각 자료형·기본값은 3.2를 따른다. scope_product_ids도 이 filters에만 둔다. Product Tool은 등록 사양·SKU·재고·판매량을 조회하고 금액의 할인·총액·예산 충족 여부를 계산하지 않는다.

search_products의 data는 candidates: Candidate[], unavailable: UnavailableCandidate[]다. Candidate={product: Product, variants: Variant[]}이며 variants는 해당 수량 구매 가능한 SKU만 포함한다. UnavailableCandidate={product_id: ProductId, reason: OUT_OF_STOCK 또는 INSUFFICIENT_STOCK}. 최종 추천 개수 제한은 평가 후 서버가 적용한다.

### 7.2 Quote Tool과 추천 예산 판정

| 함수 | 입력 | 출력 |
|---|---|---|
| calculate_quote(items, card_company=None) | QuoteItem[] 필수, 카드사는 string 또는 null | 성공 data.quote: Quote. 미등록 data.missing_skus: SKU[], 재고 부족 data.stock_issues: StockIssue[] |
| price_candidates(offers, card_company=None) | offers: QuoteItem[] 필수. 각 행은 서로 대체 가능한 SKU 후보 | data.prices: CandidatePrice[]; 후보를 장바구니처럼 합산하지 않음 |

CandidatePrice={sku: SKU, quantity: Quantity, unit_price: Money, subtotal: Money, discount_rate: DecimalRate, discount_amount: Money, total: Money, promotion_id: string nullable, promotion_status: enum, stock_quantity: integer>=0, price_updated_at: datetime}. 모든 키 필수다. 두 함수는 같은 가격·정책 검증·반올림 함수를 사용한다.

price_candidates는 조회 시점에 구매 가능한 후보만 prices에 담는다. 미등록·재고 부족으로 탈락한 대체 후보는 issues에 기록하고 다른 후보는 평가를 계속한다. 카드사 중복 정책 같은 공통 설정 오류는 요청 전체를 실패시킨다. calculate_quote는 확정 장바구니이므로 어느 품목이든 문제가 있으면 정상 견적을 완료하지 않는다.

추천 처리 순서는 다음과 같다.

1. 서버가 Product Tool에 사양·브랜드·용량·수량·상품 범위를 전달해 후보를 조회한다.
2. Quote Tool이 후보 SKU의 가격·카드 정책을 확인하고 후보별 금액을 계산한다.
3. 서버가 PER_UNIT이면 후보의 total/quantity, TOTAL이면 total을 budget.amount와 비교한다. 나눗셈 반올림 오차를 피하려면 PER_UNIT은 total <= amount×quantity로 판정한다.
4. 통과한 상품 안에서 필요할 때 RAG를 사용하고, 용도 적합성·판매량·가격 기준으로 최종 최대 5기종을 선택한다.
5. 대표 가격은 통과한 구매 가능 SKU의 최저 판매가다. 카드 할인으로 예산을 충족했다면 적용 조건과 계산된 금액도 안내한다.

할인 전 가격만으로 후보를 먼저 탈락시키지 않는다. Product Tool이나 Agent가 할인식을 별도로 복제하지 않는다. 카드사별 단일 정책·품목별 소계 할인 반올림·한국 날짜 판정 원칙을 유지한다. 재고 부족이면 다품목 정상 견적 완료를 보류한다.

### 7.3 RAG Tool

search_product_documents(query, product_ids, top_k_per_product=2)를 사용한다. query는 비어 있지 않은 string, product_ids는 ProductId[] 필수, top_k_per_product는 양의 integer다. null은 허용하지 않는다. 빈 상품 범위를 전체 검색으로 바꾸지 않는다.

반환 data는 hits: InternalHit[], has_evidence: boolean이다. InternalHit의 필수 필드는 product_id: ProductId, chunk_id·document_id·content: string, metadata: {source_file: string, page_number: integer>=1}, distance: number다. 내부 원문과 식별자는 공개 Source 객체로 변환해 제공한다. qwen3-embedding:0.6b·1024차원·유한값을 확인하고 상품 범위를 제한해 코사인 거리로 검색한다. 관련도 기준은 평가 질문으로 조정한다.

## 8. DB 연결과 문서 경계

SQLAlchemy Core + psycopg 3을 사용하고 연결 풀은 SQLAlchemy Engine에서 관리한다. SQL·Vector·Session Repository만 DB에 접근한다. 기존 public·rag 테이블과 승인형 ETL을 유지하며 신규 상담 테이블·카드사 고유 제약은 번호가 있는 SQL로 추가한다. RAM·용량 등의 API 이름은 기존 ram_capacity·storage_capacity 컬럼에 명시적으로 매핑한다.

DB 연결·트랜잭션은 조회 구간에서 관리하고 생성 LLM 대기 중 유지하지 않는다. 세션 큐·저장 구조·만료 정리는 ④, 장애별 처리와 재시도는 ⑤에서 정의한다. 신규 DB 테이블 DDL과 패키지 버전은 구현 단계에서 확정한다.

## 9. 계약 검증과 개정 내역

구현 후에는 요청 자료형·필수값·null, SKU 및 가격 일치, 옵션별 RAM 구분, 추천 범위, 금액 합계, 출처 참조, NEED_INPUT 선택지, 직접 API의 상태 비변경, SSE 최종 이벤트, 중복 요청을 검증한다. 실제 실행 결과는 ⑥ 테스트 문서에 기록한다.

0.2 개정: SSE 중간 스트림 복원 후순위화, 공개 출처 4필드로 축소, 상태·예외 상세 문서 분리, Product·Quote·서버의 예산 판정 역할 명시, scope_product_ids를 filters 한곳으로 통일, 필드 계약 보완, 추천·추가 질문·오류의 완전한 JSON 추가.

