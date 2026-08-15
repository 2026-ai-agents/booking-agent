"""v0.3 시연: 쓰기 직전에 멈추고, 사람의 결정으로 갈린다.

서버의 /chat으로 예약을 요청하면 그래프가 confirm 노드에서 interrupt로
멈추고, /chat 응답은 answer 대신 interrupt 페이로드가 된다. /confirm이
Command(resume)로 결정을 되돌려주면 그 자리에서 이어진다.

  1부 (기본): 예약 요청 → interrupt → 승인 → 도구 실행·접수
  2부 (--decline): 예약 요청 → interrupt → 보류 → 도구 미실행, 조건 재질문

--decline은 db에 아무것도 쓰지 않았다는 것까지 SQL로 확인한다.
"""

import json
import sys
import uuid

import httpx
import psycopg

APP = "http://localhost:8000"
DB = "postgresql://booking:booking@db:5432/bookingdb"
# 매 실행 새 thread — 데모를 몇 번을 돌려도 같은 장면이 재현된다
THREAD = f"demo-{'decline' if '--decline' in sys.argv else 'approve'}-{uuid.uuid4().hex[:6]}"


def chat(message: str) -> dict:
    r = httpx.post(f"{APP}/chat", json={
        "customer_id": 2, "customer_name": "박지훈",
        "thread_id": THREAD, "message": message,
    }, timeout=120)
    r.raise_for_status()
    print(f"[손님] {message}")
    return r.json()


def confirm(approved: bool, reason: str | None = None) -> dict:
    r = httpx.post(f"{APP}/confirm", json={
        "thread_id": THREAD, "approved": approved, "reason": reason,
    }, timeout=120)
    r.raise_for_status()
    return r.json()


def count_rows() -> int:
    with psycopg.connect(DB) as conn:
        return conn.execute(
            "SELECT count(*) FROM reservations WHERE customer_id = 2 AND res_date >= CURRENT_DATE"
        ).fetchone()[0]


before = count_rows()
resp = chat("모레 저녁 8시에 2명, 창가 자리로 예약해 주세요. 되는 창가 테이블 아무거나요.")
while resp["interrupt"] is None:
    # 상담사가 되물었다면(테이블 선택 등) 구체적으로 답해 확정 요청까지 간다
    print(f"[상담사] {resp['answer']}\n")
    resp = chat("네 그 테이블로 진행해 주세요.")

print("\n=== 그래프가 멈췄다: /chat이 answer 대신 interrupt를 돌려줬다 ===")
print(json.dumps(resp["interrupt"], ensure_ascii=False, indent=2))
print(f"(이 시점 db 예약 행: {count_rows() - before}개 — 아직 아무것도 쓰지 않았다)\n")

if "--decline" in sys.argv:
    print("=== 보류를 되돌려준다: Command(resume={approved: False, reason: 7시로}) ===\n")
    final = confirm(False, "8시 말고 7시로 바꾸고 싶어요")
    if final["interrupt"]:
        # 보류 사유를 읽은 상담사가 바뀐 조건으로 새 확인을 요청하며 다시 멈추기도 한다
        print("상담사가 바뀐 조건으로 다시 확인을 요청하며 멈췄다:")
        print(json.dumps(final["interrupt"], ensure_ascii=False, indent=2))
    else:
        print(f"[상담사] {final['answer']}\n")
    print(f"보류 후 db 예약 행: {count_rows() - before}개 — 처음 요청(20:00)은 실행되지 않았다")
else:
    print("=== 승인을 되돌려준다: Command(resume={approved: True}) ===\n")
    final = confirm(True)
    print(f"[상담사] {final['answer']}\n")
    print(f"승인 후 db 예약 행: {count_rows() - before}개 — 이제야 썼다")
