# 백엔드 구현 (1~3차)

## 이번 범위

- `POST /quote`: 실제 SKU 가격·재고를 조회하는 다품목 견적 API
- `POST /recommend`: 브랜드·예산·RAM·용량·사양·수량 조건별 최대 5기종 추천
- Product Tool의 검색·비교·최근 3개월 판매 순위 및 RAG Tool
- 용도 지정 시 실제 설명서 검색과 로컬 모델 적합성 평가
- 세션 생성·초기화 API, `/chat` SSE, LangGraph 고정 대화 흐름
- PostgreSQL 대화 상태·최근 5쌍·추천 목록 2회 저장, 30분 만료
- 상담별 FIFO·요청 중복 방지·초기화 후 늦은 결과 저장 차단
- 카드사 단일 정책 확인, 한국 날짜 기준 기간 판정, SKU 소계 할인 반올림
- 중복 SKU 수량 합산, 수량·금액 범위 검증, 미등록/재고 부족 시 견적 보류
- `ProductTool.get_product_details`: RAM·용량·색상별 전체 옵션 조회
- 공통 Repository: SQLAlchemy Core + psycopg 3, 읽기 전용 스냅샷
- `GET /health`, Swagger `/docs`, Docker 실행과 자동 테스트

기존 DB 데이터와 Streamlit 관리자 코드는 변경하지 않는다. 조회 결과는 재고 예약이나 결제를 의미하지 않는다.

## 실행

기존 프로젝트 루트의 `.env`와 DB를 그대로 사용한다. Python/Node 설치는 필요하지 않으며 Docker Desktop이 실행 중이어야 한다.

```powershell
docker compose -f compose.yaml -f deploy/compose.backend.yaml up -d --build backend
```

- API 문서: http://localhost:8000/docs
- DB 연결은 컨테이너 내부 `db:5432`를 사용한다.
- 포트는 로컬 컴퓨터에만 열었다. 외부 공개·고객 UI는 후속 단계다.
- 생성 모델 기본값은 설치된 `qwen2.5:3b`, 임베딩은 기존 `qwen3-embedding:0.6b`다. `CHAT_MODEL` 환경 변수로 생성 모델을 바꿀 수 있다. 모델 연결을 확인하지 못하면 `/health`가 HTTP 503을 반환한다. `/quote`와 용도 없는 직접 추천은 생성 모델을 사용하지 않는다.

예시: `/docs` → `POST /quote` → Try it out에서 실행한다.

```json
{
  "request_id": "44444444-4444-4444-8444-444444444444",
  "items": [{"sku": "RM-15C-BK-4-128", "quantity": 3}],
  "card_company": null
}
```

## 테스트

```powershell
docker compose -f compose.yaml -f deploy/compose.backend.yaml run --rm --no-deps backend python -m pytest backend/tests -q
docker compose -f compose.yaml -f deploy/compose.backend.yaml run --rm --no-deps -e RUN_DB_TESTS=1 backend python -m pytest backend/tests -q
```

두 번째 명령은 현재 적재된 `RM-15C` 상품을 읽기 전용으로 확인한다. DB가 준비되지 않은 새 환경에서는 실행하지 않는다.

추천 예시 (`/docs`의 `POST /recommend`에서 실행):

```json
{
  "request_id": "33333333-3333-4333-8333-333333333333",
  "filters": {
    "budget": {"amount": 500000, "scope": "PER_UNIT"},
    "purpose": "배터리가 오래 가는 휴대폰"
  },
  "limit": 5
}
```

추천 순서: DB 필터 → Quote Tool 후보별 할인·예산 판정 → 후보 안에서 설명서 검색 → 용도 적합성 평가 → 동점일 때 판매량·판매가 순. 대표 가격은 조건을 충족한 옵션의 최저 판매가이며 할인 후 금액과 구분해 안내한다. 모델 결과에 미등록 상품·중복 평가가 있으면 오류로 처리한다. 문서 출처는 짧은 발췌 요약만 제공한다.

`RAG_MAX_DISTANCE` 초기값은 코사인 거리 0.65다. 모델 적합성 점수(0~3)와 거리 기준은 시나리오 평가로 추가 조정해야 하며, 추천 품질이 검증 완료된 상태는 아니다.

## 다음 구현 순서

1. React 고객 화면과 이미지 URL 연결
2. 상담 시나리오 평가와 자연어 표현 보완
3. 신규 환경 DB·모델 자동 준비, 카드사 고유 제약·적재 검증, 공개 HTTPS

## 채팅 사용

1. `/docs`의 `POST /sessions`에서 `{}`를 실행한다.
2. 응답의 `data.session.session_id`를 복사한다.
3. `POST /chat` 예시의 session_id를 바꾸고 message에 질문을 넣는다.
4. 질문을 추가할 때 session_id는 유지하고 request_id는 새 UUID로 바꾼다.
5. 추천 후 “두 번째 상품으로 3대 견적 내줘” → 옵션 선택 → “5대로 변경해줘”를 이어갈 수 있다.

화면의 옵션 선택은 options.message를 그대로 전송한다. 추천 대표 SKU는 자동 구매 확정으로 사용하지 않는다. 같은 요청 ID·문장은 기존 완료 결과를 재전달하며, 다른 문장은 409다. 직접 `/quote`, `/recommend`는 상담에 저장하지 않는다.

상담 테이블은 시작할 때 `backend/migrations/001_sessions.sql`을 순서 기록과 함께 자동 적용한다. 기존 public/rag 데이터는 바꾸지 않는다. 모델 대기 중에는 DB 연결을 보유하지 않는다.

**현재는 Uvicorn 단일 worker로 실행한다.** 상담별 FIFO는 이 프로세스가 관리하고 저장은 DB 버전으로 검증한다. 여러 worker/서버로 확장할 때는 공유 큐가 필요하다. 서버 재시작 시 중단 요청을 자동 재실행하지 않는다. 자동 스트림 복구도 포함하지 않는다.

접근은 30분 만료 시 즉시 차단한다. 만료한 대화 원문·목록·상태는 60초 간격으로 정리하고, 만료 ID는 하루 뒤 삭제한다. 삭제 후에는 410 대신 미등록 404가 반환될 수 있다.

채팅 안내문은 검증된 Tool 데이터로 구성하며 모델이 금액·사양을 새로 작성하지 못하도록 출력 문장을 제한했다. 최종 모델 호출 실패 시 정상 결과를 저장하지 않는다. 자유로운 장문 상품 설명과 모든 자연어 표현의 품질 검증은 후속 범위다.

실제 모델 상담 검증(수동):

```powershell
docker compose -f compose.yaml -f deploy/compose.backend.yaml exec -T backend python -m backend.tests.smoke_chat
```

고객 UI, 자동 데이터 적재와 외부 공개 배포는 아직 구현하지 않았다.
