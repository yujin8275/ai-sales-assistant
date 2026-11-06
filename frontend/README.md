# 고객 화면

React + TypeScript + Vite. Nginx에서 정적 화면을 제공하고 `/api`는 백엔드로 전달한다. SSE 버퍼링은 끈다.

프로젝트 루트에서 실행:

```powershell
docker compose -f compose.yaml -f deploy/compose.backend.yaml up -d --build backend web
```

접속: http://localhost:8080 · 상담: http://localhost:8080/chat

위 명령은 기존 개발 환경용입니다. 새 PC 실행과 외부 공개는 루트 README.md를 따릅니다.

홈 실제 상품·이미지, 상담 입력·진행 표시, 추천 카드, 전체 SKU 옵션, 견적·할인·출처, 서버 확정 조건 패널을 구현했다. 금액·조건을 화면에서 추측하지 않는다. 선택 버튼도 채팅 문장으로 전송한다.

새로고침하면 화면의 대화는 새로 시작한다. 브라우저에 상담 원문이나 세션을 저장하는 기능은 현재 없다. 새 상담 버튼으로 서버 상담을 초기화한다.

검증: TypeScript 검사와 운영 빌드, 백엔드 76개 테스트, 실제 브라우저 홈 진입·상품 이미지·추천 상담·확정 예산 표시 확인. 옵션→견적 및 모바일 실제 브라우저 종합 검증은 후속으로 수행한다.
