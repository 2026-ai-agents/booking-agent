"""v1.0 시연: 사장 어시스턴트 — 고정 도구, 자유 SQL, 그리고 세 겹 방어.

1부: /admin/chat으로 실제 질문 두 개
   · 고정 도구가 답하는 질문 (승인 대기 현황)
   · 고정 도구 밖의 집계 — 어시스턴트가 SELECT를 직접 작성한다
2부: 방어를 도구 수준에서 직접 두드린다 (결정적)
   · DELETE → SELECT 한정에 거부
   · "SELECT 1; DELETE …" → 한 문장 한정에 거부
   · SELECT로 시작하지만 쓰는 setval() → READ ONLY 트랜잭션이 거부
"""

import json

import httpx

from agent.admin_tools import run_admin_tool

APP = "http://localhost:8000"
HEADERS = {"x-admin-password": "changeme"}


def ask(message: str) -> None:
    r = httpx.post(f"{APP}/admin/chat", headers=HEADERS,
                   json={"thread_id": "demo-admin", "message": message}, timeout=120)
    r.raise_for_status()
    print(f"[사장] {message}")
    print(f"[어시스턴트] {r.json()['answer']}\n")


print("=== 1부: 사장 어시스턴트에게 묻는다 ===\n")
ask("지금 승인 대기 중인 예약이 몇 건이고 어떤 건들이야?")
ask("다음 일주일 날짜별로 몇 팀·몇 명이 오는지 집계해줘. 인원 많은 날 순으로.")

print("=== 2부: run_sql의 세 겹 방어를 직접 두드린다 ===\n")
for label, query in [
    ("쓰기 시도", "DELETE FROM reservations"),
    ("다중 문장", "SELECT 1; DELETE FROM reservations"),
    ("SELECT 위장 쓰기", "SELECT setval('reservations_id_seq', 999999)"),
]:
    result = json.loads(run_admin_tool("run_sql", json.dumps({"query": query})))
    print(f"[{label}] {query}")
    print(f"  → {result.get('error', result)}\n")
