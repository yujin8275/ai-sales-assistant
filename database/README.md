# ABC Electronics | Database & ETL

AI 판매·추천 에이전트에 사용할 **상품·재고·가격·판매 데이터와 제품설명서 검색 데이터**를 관리하는 모듈입니다.  
관리자는 PDF·Excel을 등록하고 변경사항을 검토한 뒤 승인하여 PostgreSQL에 반영합니다.

## 1. 기술 스택

- **DB:** PostgreSQL 18 + pgvector (RDB 10개 테이블, RAG 1개 테이블)
- **관리 화면:** Streamlit
- **데이터 처리:** Python, pdfplumber, PyMuPDF, openpyxl
- **임베딩:** Ollama `qwen3-embedding:0.6b`
- **실행 환경:** Docker Compose (Windows PowerShell 기준)

## 2. 프로젝트 구조

```text
ai-sales-assistant/
├── compose.yaml              # PostgreSQL + Streamlit 컨테이너
├── deploy/admin/Dockerfile
├── deploy/admin/requirements.txt
├── .env                      # 로컬 설정 (Git에 업로드하지 않음)
└── database/
    ├── app.py                # Streamlit 관리 화면
    ├── pipeline.py           # ETL 실행 및 처리 이력
    ├── extract.py            # PDF·Excel 추출
    ├── transform.py          # 정규화·검증·DB 비교
    ├── database.py           # PostgreSQL 조회·UPSERT
    ├── rag.py                # 설명서 임베딩
    ├── images.py             # 카탈로그 이미지 추출·저장
    ├── sql/                  # DB 생성·검증 SQL
    └── data/
        ├── inbox/            # 신규 입력: catalogs/, manuals/, sales/
        ├── processed/
        │   ├── import_preview.json   # 최신 분석 결과 (갱신)
        │   ├── import_history.json   # DB 저장·보관 이력 (누적)
        │   └── snapshots/            # 분석별 JSON (누적)
        ├── product_images/   # 추출된 PNG
        └── archive/          # 저장 완료 원본 파일
```

## 3. 최초 실행

**사전 준비:** Docker Desktop과 Ollama를 설치·실행하고, 프로젝트 루트에 `.env` 파일을 준비합니다. 호스트 PC에 Python/Conda 설치는 필요하지 않습니다.

`.env` 주요 설정 예시(비밀번호는 각자 설정):

```dotenv
POSTGRES_PASSWORD=YOUR_PASSWORD
DB_HOST=127.0.0.1
DB_PORT=5433
DB_NAME=ai_sales
DB_USER=ai_user
DB_PASSWORD=YOUR_PASSWORD
OLLAMA_EMBED_MODEL=qwen3-embedding:0.6b
```

프로젝트 최상위 폴더에서 PowerShell 실행:

```powershell
ollama pull qwen3-embedding:0.6b
docker compose up -d --build app
docker compose ps
```

**새 DB를 생성한 팀원만** 다음 스키마 SQL을 최초 1회 실행합니다. 기존 테이블이 생성되어 있다면 생략합니다.

```powershell
docker cp .\database\sql\01_create_rdb.sql ai_sales_db:/tmp/01_create_rdb.sql
docker cp .\database\sql\02_create_vector.sql ai_sales_db:/tmp/02_create_vector.sql

docker compose exec -T db psql -U ai_user -d ai_sales -v ON_ERROR_STOP=1 -f /tmp/01_create_rdb.sql
docker compose exec -T db psql -U ai_user -d ai_sales -v ON_ERROR_STOP=1 -f /tmp/02_create_vector.sql
```

관리 화면: **http://localhost:8501**

## 4. 데이터 등록 및 저장 과정

1. **파일 등록:** 카탈로그 PDF → `inbox/catalogs/`, 설명서 PDF → `inbox/manuals/`, 판매·재고 Excel → `inbox/sales/`.
2. **분석:** Streamlit에서 **「신규 파일 분석」** 클릭. 텍스트·이미지 추출, 정규화·검증, 기존 DB와 비교한 INSERT/UPDATE/SKIP 내역을 표시합니다.
3. **JSON 보관:** `import_preview.json`은 최신 결과로 갱신하고, 같은 분석 결과를 `snapshots/작업ID.json`으로 누적 보관합니다. **분석만으로 DB는 변경되지 않습니다.**
4. **승인·저장:** 관리자가 확인 후 승인하면 상품·SKU·가격·재고·판매 정보는 `public` 스키마에, 설명서 청크·임베딩은 `rag` 스키마에 반영합니다. 제품 사진은 PNG로 저장하고 DB에는 경로만 기록합니다.
5. **이력·원본 보관:** 성공한 저장 내역은 `import_history.json`에 누적하고, 원본 파일은 `inbox/`에서 `archive/`로 이동합니다. 보관 실패 시 웹에서 재시도할 수 있습니다.

> **기존 상품은 일괄 삭제하지 않습니다.** 신규·변경 데이터를 중심으로 갱신하며, 파일 분석 결과를 승인하기 전까지 DB에 쓰지 않습니다. 최초 신규 DB 적재에는 원본 PDF·Excel이 필요합니다.

## 5. 운영 명령어

```powershell
# 평소 실행
docker compose up -d app

# 코드/라이브러리 변경 후 재빌드
docker compose up -d --build app

# 앱 로그 확인
docker compose logs --tail=100 app

# 등록된 상품 및 이미지 경로 건수 확인
docker compose exec -T db psql -U ai_user -d ai_sales -P pager=off -c "SELECT COUNT(*) AS products, COUNT(product_image_path) AS images FROM public.products;"

# 종료 (데이터 볼륨 유지)
docker compose stop
```

**주의사항:** `docker compose down -v`는 DB 볼륨을 삭제할 수 있으므로 사용하지 않습니다. `.env`는 공유 저장소에 올리지 않습니다. `snapshots/`는 ETL 분석 이력이지 **DB 전체 백업이 아니므로**, PostgreSQL과 `database/data/`를 별도로 백업해야 합니다. 기존 데이터의 이미지 경로를 보완하기 위해 한 번 실행했던 `product_image_paths.sql`은 **신규 적재 과정에서 필요하지 않습니다.**
