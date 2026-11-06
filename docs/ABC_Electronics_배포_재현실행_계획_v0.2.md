# ABC Electronics 배포 및 재현 실행 계획

버전 0.2 / 2026-11-05 / 무료 예산·보유 GPU·기업용 운영 구조 선호 반영  
상태: 구현 기준안. 실제 서버 구성·GPU 모델 성능 검증·외부 배포는 아직 하지 않았다.

## 1. 운영 방향

기업용 단일 서버 배포와 비슷한 Linux 컨테이너 구성으로 개발한다. 현재 무료 예산에서는 Windows 노트북의 Docker Desktop·WSL2를 실행 기반으로 삼고 GPU를 활용해 모델을 검증하는 방안을 제안한다. 고객에게는 HTTPS 공개 주소를 제공하고, 추후 상시 운영 서버가 확보되면 같은 구성과 고정된 이미지를 옮겨 실행할 수 있도록 한다.

노트북 실행은 개인 PC·Docker·인터넷이 켜진 동안 접속 가능한 시연 환경이다. 클라우드 상시 운영 서버와 동일한 가용성을 의미하지 않는다. ‘기업 프로젝트와 비슷함’의 기준은 서비스 분리·재현 빌드·명시적 DB 변경·로그·자동 테스트·운영 점검으로 정의한다.

## 2. 반영한 선택과 장비

| 항목 | 내용 |
|---|---|
| 고객 화면 | React + TypeScript + Vite 확정. 기존 Streamlit은 관리자 데이터 적재 화면으로 유지 |
| 예산 | 무료만 사용. 유료 서버·GPU 인스턴스·도메인을 자동 구매하지 않음 |
| 공개 주소 | 보유 도메인 없음. 무료 제공 HTTPS 주소 우선 |
| 보유 장비 | NVIDIA GeForce RTX 5070 Laptop GPU, GPU 메모리 8151 MiB 확인. 사용자 제공 CPU 정보는 고전력 i7 |
| 성능 검증 | 초기 CPU 검토 선택 이후 보유 GPU를 확인했다. 실제 노트북에서는 GPU 실행을 우선 검증하는 기준안을 제안. CPU 실행 경로는 다른 PC의 재현용으로 유지 |
| 응답 기준 | 전체 요청 60초 유지. 장비 사양만으로 통과를 보장하지 않고 실제 모델·시나리오로 검증 |

## 3. 운영 구조

`고객 HTTPS → 무료 공개 접속 경로 → web·역방향 프록시 → /api backend → db·ollama`

| 서비스 | 역할 |
|---|---|
| web | React 빌드 결과 제공, /api를 backend로 전달, SSE 전달 유지. Vite 개발 서버를 운영 서버로 사용하지 않음 |
| backend | FastAPI·LangGraph·SQLAlchemy Core 상담 서버. 실제 SQL·벡터·세션 저장은 공통 Repository 사용 |
| db | 기존 PostgreSQL 18·pgvector. 상품·벡터·상담 데이터 영속 볼륨 |
| ollama | 컨테이너 안에서 생성·임베딩 모델 실행. GPU 실행 프로필과 CPU 재현 경로 분리 |
| init | 빈 환경의 초기 스키마·샘플 데이터·모델 준비. 기존 데이터·비밀번호·볼륨을 유지 |
| admin | 기존 Streamlit 승인 적재. 별도 실행 프로필로 고객 공개 경로와 분리 |

기본 컨테이너 주소는 DB_HOST=db, OLLAMA_URL=http://ollama:11434다. 현재 host.docker.internal의 Windows Ollama에 의존하는 설정을 새 실행 구성에서 분리한다. 외부에는 고객용 웹·API 경로만 제공하고 DB·모델·관리자 화면은 내부에서 관리한다.

## 4. 무료 공개 접속 기준안

ngrok 무료 HTTPS 개발용 주소를 우선 검토한다. 계정에 할당된 무료 도메인을 사용해 도메인 구매 없이 외부 접속할 수 있으며 SSE 전송을 실제 앱으로 확인한다. 계정 가입과 인증 토큰의 최초 등록은 필요하다. 토큰은 실행 환경에서 관리하고 저장소에 포함하지 않는다. 무료 사용량 제한과 첫 방문 안내 화면을 배포 안내에 명시한다.

Cloudflare Quick Tunnel은 SSE를 지원하지 않으므로 이 앱의 공개 경로에서 제외한다. 노트북이 꺼져도 운영되는 무료 클라우드를 우선해야 한다면, 계정·무료 자원 할당·CPU/메모리·모델 성능을 확인한 뒤 별도 실행 환경으로 정한다. 현재 유료 운영으로 조건을 바꾸지 않는다.

## 5. 기업용 운영에 맞춰 갖출 최소 구성

- 같은 저장소의 frontend/·backend/·database/·docs/·scripts/를 기준으로 관리한다.
- 기본 Compose와 GPU·외부 공개·운영용 설정을 분리하고 나중에 호스트·도메인 설정을 교체할 수 있게 한다.
- 패키지 잠금 파일·검증한 컨테이너 이미지·모델 버전·초기 DB·이미지 데이터를 배포 버전에 기록한다.
- 빌드 → 자동 테스트 → 같은 이미지 실행 순서를 실행 스크립트로 통일한다. 원격 CI/CD는 필요 시 추가한다.
- 상태 점검·컨테이너 재시작 정책·요청 ID 로그·세션별 순서·중복 방지·DB 및 모델 영속 볼륨을 적용한다.
- 번호가 있는 DB 변경 파일과 적용 기록을 사용하고 새 실행 때 기존 테이블을 재생성하지 않는다.

현재 규모에는 단일 서버 Compose 구성을 사용한다. Kubernetes·여러 서버 분산 운영·별도 메시지 브로커 도입은 첫 버전 범위에 포함하지 않는다.

## 6. 전달받은 사람이 실행할 때

Docker가 준비된 환경에서 실행 스크립트 한 번으로 패키지 빌드·DB·모델 준비를 수행하는 것을 목표로 한다. Python·Node·PostgreSQL·Ollama 개별 설치와 PC별 API 주소 수정을 없앤다. 새 환경에서만 기본 설정·비밀번호·데이터를 자동 준비하며 기존 .env와 DB 볼륨을 재사용한다.

GPU 사용에는 호스트의 NVIDIA 드라이버·WSL2·Docker GPU 지원이 필요하다. GPU가 없는 사람도 CPU 경로로 같은 코드를 실행할 수 있게 하되 처리 속도는 별도 확인한다. 최초 모델 다운로드에는 인터넷·저장 공간이 필요하다. 외부 공개는 계정 인증을 한 번 준비해야 하며 계정 토큰을 배포 파일에 넣지 않는다.

## 7. 참고 자료

- [Docker Compose 단일 서버 운영](https://docs.docker.com/compose/how-tos/production/)
- [Windows Docker GPU 지원](https://docs.docker.com/desktop/features/gpu/)
- [Ollama Docker](https://docs.ollama.com/docker)
- [ngrok 무료 주소·사용량·방문 안내](https://ngrok.com/docs/pricing-limits/free-plan-limits)
- [ngrok SSE 전달 안내](https://ngrok.com/compare/cloudflare-tunnel)
- [Cloudflare Quick Tunnel 제한](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)

0.2 개정: 고객 화면 기술 확정·무료 예산·무료 주소 선호 반영. 노트북 GPU 실측 정보를 기록하고 기업용 구조를 로컬에서 재현하는 무료 시연 기준안으로 구체화.
