# ABC Electronics — 데이터 관리 모듈 (Docker 공통 실행)

## 1. 파일을 배치하는 위치

이 파일과 `Dockerfile`, `compose.yaml`, `.dockerignore`를 **프로젝트 최상위**
`ai-sales-assistant/`에 놓습니다. 기존 `compose.yaml`만 교체하고 나머지 세 파일은 추가/교체합니다.
기존 Python 6개, `requirements.txt`, `.env`, SQL 3개는 **수정하지 않습니다**.

```text
ai-sales-assistant/
├── compose.yaml              # 교체 (db + app)
├── Dockerfile                # 추가
├── .dockerignore             # 추가
├── .env                      # 기존 유지, 비밀번호 실제값 필요
├── requirements.txt          # 기존 유지
├── DATABASE_SETUP.md         # 본 설명서로 교체
└── database/
    ├── __init__.py
    ├── app.py
    ├── pipeline.py
    ├── extract.py
    ├── transform.py
    ├── rag.py
    ├── database.py
    ├── sql/                  # 기존 SQL 유지
    └── data/
        ├── inbox/
        │   ├── catalogs/     # 신규 카탈로그 PDF
        │   ├── manuals/      # 신규 제품설명서 PDF
        │   └── sales/        # 최신 판매 Excel (동시에 하나)
        ├── archive/          # 저장 성공 후 이동
        └── processed/        # JSON 미리보기/이력
```

> **중요:** `compose.yaml`의 `postgres_data:/var/lib/postgresql`은 기존과 같습니다.
> `docker compose down -v`를 실행하지 마세요. DB 볼륨을 삭제할 수 있습니다.
> 기존에 성공적으로 생성한 PostgreSQL 테이블 11개를 다시 생성하지 않습니다.

## 2. 기존 `.env` 설정 (비밀번호를 공유하지 마세요)

```dotenv
POSTGRES_PASSWORD=기존_실제_비밀번호
DB_HOST=127.0.0.1
DB_PORT=5433
DB_NAME=ai_sales
DB_USER=ai_user
DB_PASSWORD=기존_실제_비밀번호
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_EMBED_MODEL=qwen3-embedding:0.6b
```

`POSTGRES_PASSWORD`와 `DB_PASSWORD`는 기존 데이터베이스의 **동일한 실제 비밀번호**입니다.
컨테이너 안에서는 Compose가 `DB_HOST=db`, `DB_PORT=5432`,
`OLLAMA_URL=http://host.docker.internal:11434`로 자동 덮어씁니다.
따라서 `.env`를 팀원마다 Docker 주소로 고칠 필요는 없습니다.

## 3. 팀원별 준비물

- Docker Desktop 설치 및 실행 (WSL2 기반 Linux 컨테이너)
- 로컬 Windows Ollama 설치/실행 (실제 RAG 저장 시 필요)
- `ollama pull qwen3-embedding:0.6b`로 모델 설치 (최초 1회)
- 동일한 코드, 각자 설정한 유효한 `.env`, 동일한 PDF·Excel 샘플 준비
- Python/Conda를 Windows에 따로 설치하거나 활성화할 필요 없음

> Ollama가 Windows에서 `127.0.0.1` 주소에만 바인딩되어 있으면
> Docker 컨테이너에서 `host.docker.internal`로 접속되지 않을 수 있습니다.
> 아래 접속 검사를 먼저 실시하세요. 접속 실패 시 Docker Desktop/Windows/Ollama의
> 네트워크 설정을 확인해야 합니다. Ollama는 기본적으로 인증이 없으므로
> `OLLAMA_HOST=0.0.0.0`로 외부 인터페이스에 공개하는 것은 신중히 결정하세요.

## 4. PowerShell 실행 (프로젝트 최상위에서)

### ① 설정 문법 확인

```powershell
docker compose config --quiet
```

### ② Python 환경 이미지를 빌드하고 UI와 DB 실행

```powershell
docker compose up -d --build app
docker compose ps
```

첫 빌드는 Python 이미지와 패키지를 다운로드하므로 인터넷이 필요합니다.
웹 화면: http://localhost:8501

### ③ DB에 저장하지 않고 PDF·Excel 분석/검증만 실행

```powershell
docker compose run --rm app python -m database.pipeline
```

이 명령은 `inbox/` 파일을 읽고 기존 DB와 비교해
`database/data/processed/import_preview.json`을 생성합니다.
**DB 변경 또는 archive 이동은 하지 않습니다.**

### ④ 로컬 Ollama 상태 확인 (Windows PowerShell)

```powershell
ollama list
ollama pull qwen3-embedding:0.6b
```

### ⑤ Docker 컨테이너 → Windows Ollama 연결 확인

```powershell
docker compose exec app python -c "import os,requests; u=os.environ['OLLAMA_URL']; r=requests.get(u+'/api/tags',timeout=10); print(r.status_code); print(r.text[:600]); r.raise_for_status()"
```

정상이라면 HTTP `200`과 Ollama 모델 목록이 표시됩니다.
연결이 안 돼도 ③ 미리보기는 실행할 수 있으나, 설명서를 실제 저장하려면 Ollama 연결이 필요합니다.

### ⑥ DB 저장은 Streamlit 화면에서 직원 승인 후 실시

브라우저 http://localhost:8501 에서
`신규 파일 분석 → 검증 결과 확인 → 승인하고 PostgreSQL에 저장` 순서로 진행합니다.
저장 성공 후 파일이 `archive/`로 옮겨집니다.

## 5. 자주 쓰는 명령어

```powershell
# 로그 확인
docker compose logs --tail=100 app

# 코드 또는 requirements.txt가 바뀐 뒤 이미지 재빌드
docker compose up -d --build app

# 실행 중인 서비스 종료 (볼륨 유지)
docker compose stop

# 다시 실행
docker compose up -d app
```

## 6. 주의사항

- 기존 DB 데이터는 별도 백업이 필요합니다. Compose 파일 이동/프로젝트 이름 변경은 볼륨 연결에 영향을 줄 수 있습니다.
- `database/data`는 Windows 폴더로 연결되어 PDF, Excel, JSON, archive 등이 컨테이너 종료 후에도 남습니다.
- 초기 RDB가 비어 있고 새로운 카탈로그 및 Excel을 함께 넣으면 한 번에 검증할 수 있습니다.
- PDF/Excel의 ID·SKU가 다른 경우 오류로 중단하며 임의 매핑하지 않습니다.
- 모든 팀원이 정확히 같은 라이브러리 버전까지 재현하려면 추후 `requirements.txt`의 버전을 고정해야 합니다. 현재는 기존 버전 범위를 유지합니다.
