# 실행 및 공개

## 현재 노트북

Docker Desktop과 현재 Ollama가 켜진 상태에서 프로젝트 폴더의 PowerShell로 실행한다.

```powershell
.\start.ps1
```

고객 화면 http://localhost:8080, API 문서 http://localhost:8000/docs. 기존 .env와 DB 볼륨은 유지한다.

## 다른 PC: Docker로 모델까지 준비

```powershell
.\start.ps1 -Portable
```

NVIDIA GPU가 Docker Desktop/WSL2에서 사용 가능한 장비:

```powershell
.\start.ps1 -Portable -Gpu
```

첫 실행에는 인터넷·디스크 공간·모델 다운로드 시간이 필요하다. Windows에 Python/Node/PostgreSQL/Ollama를 별도로 설치하지 않는다. Docker Desktop/WSL2 및 GPU 드라이버 준비는 필요하다.

새 환경의 .env는 임의 비밀번호로 생성한다. 기존 .env는 덮어쓰지 않으며 기존 DB 볼륨에 대한 비밀번호를 새로 만들지도 않는다. 상품 DB가 있으면 초기 데이터는 건너뛴다.

`deploy/seed`에는 가상 ABC Electronics 상품 45개, SKU 466개, 문서 벡터 45개의 스냅샷을 담았다. 상담 원문·상담 상태·접속 비밀번호는 포함하지 않는다. 새 DB 초기화는 한 트랜잭션으로 실행한다. 이후 데이터 갱신은 기존 관리자 승인 흐름을 사용한다.

검증 완료: 빈 별도 DB 복원, 개수/벡터 차원, 두 번째 실행 시 건너뛰기, Compose 문법, 기존 로컬 실행.
미검증: 새 Windows PC의 전체 설치, 컨테이너 Ollama 모델 다운로드·GPU 추론·120초 성능. Portable 프로필은 준비된 구성이며 새 PC 전체 재현 검증까지 완료된 것은 아니다. 이미지와 모델 태그의 내용 변경까지 방지하는 digest 고정은 후속 관리 범위다.

## ngrok 가입 후 공개 연결

1. ngrok 대시보드에서 본인의 Authtoken을 확인한다.
2. `.env.ngrok.example`을 `.env.ngrok`으로 복사하고 토큰을 그 로컬 파일에만 넣는다.
3. 현재 노트북에서 `.\start.ps1`로 고객 화면을 켠 뒤 `.\publish.ps1`을 실행한다.
4. ngrok 대시보드 또는 안내된 로그 명령에서 HTTPS 주소를 확인한다.

고객 web:80만 공개 터널로 연결한다. DB와 관리자 Streamlit 포트는 터널에 연결하지 않는다. 노트북·Docker·인터넷이 켜져 있어야 접속 가능하다. 실제 공개 주소와 외부 접속/SSE 검증은 토큰 설정 후 수행한다. 가입·결제·인증 토큰 입력은 자동으로 수행하지 않았다.

공개 연결만 종료:

```powershell
docker compose -f compose.yaml -f compose.backend.yaml -f compose.public.yaml stop ngrok
```

공식 설정 참고: https://ngrok.com/docs/using-ngrok-with/docker

## 검증 기록

- 백엔드 테스트 86개, 프런트 API 스트림 테스트 5개 통과.
- 브라우저에서 옵션 선택→수량 입력→669,000원 견적, 20대 요청→재고 13대/7대 부족→13대 재계산 2,899,000원 확인.
- 요청 중 새 상담 버튼 동작과 늦은 응답 차단을 구현했다. 실제 네트워크 강제 종료·모바일 실기기 검증은 후속으로 남는다.

