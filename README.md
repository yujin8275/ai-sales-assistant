# ABC Electronics · AI 휴대폰 구매 상담

휴대폰 **추천·비교·판매 순위·옵션/재고 조회·카드 할인 견적**을 제공하는 시연용 서비스입니다.
상품 정보는 PostgreSQL에서 조회하고, 제품 설명은 PDF 문서 검색(RAG)을 활용합니다.

## 1. 설치할 앱

- **Windows·macOS:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) 설치 후 실행합니다. Windows는 WSL 2 기반 Linux 컨테이너를 사용합니다.
- **Linux:** Docker Engine과 Docker Compose 플러그인(v2)을 설치하고, 현재 계정에서 `docker info`가 실행되도록 준비합니다.

Python·Node.js·PostgreSQL·Ollama는 별도 설치하지 않습니다.

## 2. 실행 방법

프로젝트를 내려받고 압축을 해제한 뒤, **프로젝트 폴더에서 터미널을 열어** 아래 명령을 실행합니다. DB 비밀번호 생성·시연 데이터 적재·AI 모델 다운로드가 자동으로 진행됩니다.

**Windows — 명령 프롬프트(CMD)**

```cmd
start.cmd -Portable -Admin
```

NVIDIA GPU를 사용할 수 있는 환경에서는 아래 명령을 사용합니다.

```cmd
start.cmd -Portable -Gpu -Admin
```

**macOS — 터미널 / Linux — 터미널**

```sh
sh scripts/start.sh
```

Linux에서 NVIDIA GPU와 NVIDIA Container Toolkit이 설정되어 있다면 `sh scripts/start.sh --gpu`로 실행할 수 있습니다. macOS는 기본 CPU 실행을 사용합니다.

| 접속 주소 | 용도 |
| --- | --- |
| http://localhost:8080 | 고객 화면·AI 상담 |
| http://localhost:8501 | 관리자 파일 검토·DB 저장 |
| http://localhost:8000/docs | API 확인·직접 요청 |

첫 실행에는 모델 다운로드로 시간이 걸립니다. CPU에서는 AI 응답이 느리거나 120초 제한을 넘을 수 있습니다. 다시 실행할 때도 같은 명령을 사용합니다.

**상태 확인 / 종료 — 모든 OS 공통**

```sh
docker compose -f compose.yaml -f deploy/compose.backend.yaml -f deploy/compose.portable.yaml ps
docker compose -f compose.yaml -f deploy/compose.backend.yaml -f deploy/compose.portable.yaml stop
```

## 3. 폴더·주요 파일

```text
ai-sales-assistant/
├─ README.md: 실행 방법과 프로젝트 안내
├─ start.cmd: Windows 실행 진입점
├─ compose.yaml: DB·관리자 서비스 기본 설정
├─ .gitignore / .dockerignore: 비밀 설정·생성 파일 제외
├─ backend/: FastAPI 상담 서버
│  ├─ app/main.py: API와 응답 처리
│  ├─ app/models.py: API·Tool 데이터 형식
│  ├─ app/chat.py / planner.py: 상담 흐름·실행 계획
│  ├─ app/chat_model.py: Ollama 모델 호출
│  ├─ app/sessions.py: 대화 기억·상담 상태 관리
│  ├─ app/tools.py: 상품 조회·견적 계산
│  ├─ app/repository.py: 공통 DB 접근
│  ├─ app/rag.py / knowledge.py: 문서 검색·설명 근거
│  ├─ app/recommendation.py: 추천 후보·순서 구성
│  ├─ migrations/: 상담 DB 변경 SQL
│  └─ tests/: 자동 테스트·상담 검증 시나리오
├─ frontend/: React·TypeScript 고객 화면
│  ├─ src/main.tsx: 고객 상담 UI
│  ├─ src/HomeHero.tsx / HomeProducts.tsx: 메인 화면
│  ├─ src/api.ts: API 통신
│  └─ nginx.conf: 웹 서버·API 연결 설정
├─ database/: Streamlit 관리자·데이터 적재
│  ├─ app.py: 관리자 화면
│  ├─ pipeline.py: 검토·승인·적재 흐름
│  ├─ extract.py / transform.py: PDF·Excel 추출·정규화
│  ├─ database.py: DB 저장·조회
│  ├─ rag.py / images.py: 문서 임베딩·상품 이미지 처리
│  ├─ sql/: 상품 DB 구조 SQL
│  └─ data/: 입력 파일·처리 결과·상품 이미지
├─ deploy/: 실행 환경 설정
│  ├─ compose.backend.yaml: API·고객 웹 서비스
│  ├─ compose.portable.yaml: 모델·초기 DB 자동 준비
│  ├─ compose.gpu.yaml: NVIDIA GPU 설정
│  ├─ compose.public.yaml: ngrok 연결
│  ├─ .env.ngrok.example: 토큰 값이 비어 있는 공유 양식
│  ├─ admin/: 관리자 Dockerfile·의존성
│  └─ seed/: 시연용 상품·가격·재고·문서 벡터
├─ scripts/: Windows·macOS·Linux 실행 스크립트
└─ docs/: 기능/API/Tool 명세·테스트 및 변경 기록
```

## 4. 기타

- **사용 예:** `50만원 이하 삼성 휴대폰 추천해줘` → `두 번째 제품 옵션 보여줘` → SKU 선택 후 견적 요청.
- **관리자 데이터 적재:** 더미 원본 파일(PDF·Excel)은 저장소와 별도로 제공합니다. 아래 위치에 넣고 관리자 화면(http://localhost:8501)에서 **신규 파일 분석·미리보기 → 승인·저장**을 실행하세요. 경로는 프로젝트 루트 기준입니다.

```text
database/data/inbox/
├─ catalogs/: 카탈로그 PDF
├─ manuals/: 제품 설명서 PDF
└─ sales/: 판매 데이터 Excel(.xlsx, 한 번에 1개)
```

파일을 넣는 즉시 DB에 저장되지는 않습니다. 제공된 프로젝트 양식의 파일을 사용하세요. 기본 상담 시연용 SQL 데이터는 실행 시 자동 적재됩니다.
- **모델:** 대화 `qwen3:8b`, 임베딩 `qwen3-embedding:0.6b`. 신규 Windows·macOS·Linux 장비 전체에 대한 실행 검증은 별도로 필요합니다.
- **외부 공개:** ngrok을 사용했습니다. `deploy/.env.ngrok.example`을 `.env.ngrok`으로 복사하고 본인이 발급받은 `NGROK_AUTHTOKEN`을 입력합니다. 실제 키는 공유하지 않습니다.
- **데이터:** 시연용 데이터이며 견적은 주문·재고 예약이 아닙니다. DB를 유지하려면 종료 시 `down -v`를 사용하지 마세요.

### Git 공유 범위

소스·설정 양식·문서·`deploy/seed/`의 초기 SQL·상품 이미지는 포함합니다. `inbox`는 하위 폴더 구조만 포함하며 더미 PDF·Excel 원본은 별도로 전달합니다. `.env`·`.env.ngrok`의 실제 키, 입력 원본, 처리 이력·캐시는 업로드하지 않습니다.