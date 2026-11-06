# ABC Electronics 배포 및 재현 실행 계획

버전 0.1 / 2026-11-05 / 배포 결정 대기. 실제 배포·코드 수정은 아직 하지 않았다.

## 1. 작업 위치와 목표

프로젝트 기준 경로는 `C:/Users/KDT55/PycharmProjects/PythonProject/ai-sales-assistant`다. 프런트엔드는 frontend/, 상담 서버는 backend/, 기존 적재 모듈은 database/, 명세는 docs/, 실행 보조 파일은 scripts/에 둔다.

수신자는 Docker와 Compose가 준비된 환경에서 실행 스크립트 한 번으로 빌드·실행하는 것을 목표로 한다. Python·Node·PostgreSQL·Ollama를 개별 설치하지 않도록 컨테이너로 구성한다. 현재 compose.yaml은 db와 관리자 app만 포함하므로 이 실행 목표는 추가 구현이 필요하다.

## 2. 권장 구성안

`외부 HTTPS → 고객 웹/역방향 프록시 → /api 상담 backend → PostgreSQL·Ollama`

- web: 고객 화면 빌드 결과와 HTTPS·API 경로 전달. 개발용 Vite 서버를 운영 서버로 사용하지 않는다.
- backend: FastAPI·LangGraph·SQLAlchemy Core 상담 서버. DB_HOST=db, OLLAMA_URL=http://ollama:11434를 기본으로 해 호스트 OS에 의존하지 않는다.
- db: 기존 PostgreSQL 18·pgvector와 데이터 볼륨 유지.
- ollama: 기존 임베딩 모델과 검증 후 선택한 생성 모델. 모델 파일은 영속 볼륨으로 관리.
- init: 빈 환경에서만 초기 스키마·데이터 준비와 모델 다운로드·준비 상태 확인. 기존 DB가 있으면 데이터 덮어쓰기나 볼륨 삭제를 하지 않는다.
- 관리자 app은 별도 실행 프로필로 유지하고 공개 고객 경로와 분리한다. 외부에는 고객 웹과 필요한 API만 제공한다.

## 3. 같은 환경으로 실행하기 위한 필수 작업

- npm 잠금 파일·검증된 Python 버전 목록·컨테이너 이미지·모델 버전을 고정하고 배포 버전에 기록한다.
- 새 PC에서 DB가 비지 않도록 버전이 정해진 초기 상품·SKU·가격·재고·벡터 스냅샷과 상품 이미지를 재현 패키지에 포함한다. 기존 archive·processed 파일이 로컬에만 남아 있다고 가정하지 않는다.
- 기존 .env가 있으면 유지한다. 새 환경의 DB 비밀번호 등은 실행 스크립트가 생성·보관하도록 하고 공유 코드에 실제 비밀번호를 넣지 않는다.
- 모델 최초 다운로드에는 네트워크와 저장 공간이 필요하다. CPU 실행을 기본 재현 경로로 두고, GPU 프로필은 장비와 드라이버 준비 조건을 별도 기재한다.
- 기존 dockerignore를 .dockerignore로 정리한다. 모델·DB 볼륨과 원본 전체를 이미지에 불필요하게 복사하지 않는다.
- 서버 재시작 후 데이터 유지, 빈 환경에서의 최초 실행, 외부 HTTPS·SSE, 동시 상담, 60초 제한을 확인한다.

컨테이너화는 패키지·실행 절차를 통일한다. 하드웨어 차이에 따른 처리 시간과 생성 문장까지 동일해지는 것을 보장하는 의미는 아니다.

## 4. 배포 전에 선택할 사항

고객 화면 기술, 클라우드 상시 운영 또는 PC 기반 시연, Ollama CPU/GPU 운영, 월 운영 예산, 고정 도메인 여부를 선택받는다. 비용은 희망 상한을 확인한 뒤 실제 공급자 가격으로 산정하며 현재 예상 가격을 확정하지 않는다.

고객은 URL만 열어 사용한다. 로컬 재현 담당자는 Docker 설치가 필요하다. 배포 담당자는 최초 서버 계정·도메인/DNS·HTTPS 구성을 준비해야 한다. 따라서 ‘환경설정 불필요’는 프로그램별 수동 설치·PC별 주소 변경을 자동화하는 목표로 정의한다.

60초 응답 제한은 실제 서버에서 검증해야 한다. CPU에서 충족되지 않으면 모델·서버·GPU 구성을 조정한다. 사용자가 선택한 로컬 Ollama 우선 정책을 클라우드의 Ollama 컨테이너에서도 유지할 수 있다.

## 5. 참고

- [Docker Compose 단일 서버 운영](https://docs.docker.com/compose/how-tos/production/)
- [Ollama CPU·GPU 컨테이너](https://docs.ollama.com/docker)
- [Vite 빌드 결과 배포](https://vite.dev/guide/static-deploy.html)
- [Cloudflare Quick Tunnel 제한](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/): Quick Tunnel은 SSE를 지원하지 않으므로 현재 상담 전송 방식의 배포 경로로 사용하지 않는다. 터널 시연을 선택하면 계정·도메인을 연결한 정식 터널을 대상으로 검증한다.
