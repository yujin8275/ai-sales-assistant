"""실제 로컬 모델을 쓰는 수동 실행용 상담 시나리오. pytest에서는 자동 실행하지 않는다."""
import json
import time
from uuid import uuid4

import httpx


def run():
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=135) as client:
        created = client.post("/sessions", json={})
        created.raise_for_status()
        sid = created.json()["data"]["session"]["session_id"]

        def chat(message, request_id=None):
            payload = {"session_id": sid, "request_id": request_id or str(uuid4()), "message": message}
            start = time.monotonic()
            response = client.post("/chat", json=payload)
            response.raise_for_status()
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            result = events[-1]
            print(json.dumps({"step": message, "status": result["status"], "seconds": round(time.monotonic()-start, 2),
                "recommendations": len((result.get("data") or {}).get("recommendations", [])),
                "variants": len((result.get("data") or {}).get("variants", [])),
                "total": (result.get("data") or {}).get("quote", {}).get("total"),
                "error": result.get("error")}, ensure_ascii=False), flush=True)
            assert result["status"] != "ERROR", result
            return result, payload

        first, _ = chat("50만원 이하 휴대폰 추천해줘")
        assert first["status"] == "OK" and first["data"]["recommendations"]
        second, _ = chat("두 번째 상품으로 3대 견적 내줘")
        assert second["status"] == "NEED_INPUT" and second["data"]["variants"]
        variant = next(v for v in second["data"]["variants"] if v["stock_quantity"] >= 5)
        third, payload = chat(f"{variant['sku']}로 3대 견적 내줘")
        assert third["status"] == "OK" and third["data"]["quote"]["items"][0]["quantity"] == 3
        replay, _ = chat(payload["message"], payload["request_id"])
        assert replay == third
        fourth, _ = chat("5대로 변경해줘")
        assert fourth["data"]["quote"]["items"][0]["quantity"] == 5
        reset = client.post(f"/sessions/{sid}/reset", json={"request_id": str(uuid4())})
        reset.raise_for_status()
        expired = client.post("/chat", json=payload)
        assert expired.status_code == 410
        print("RESET_AND_EXPIRED_REPLAY_OK", flush=True)


if __name__ == "__main__":
    run()
