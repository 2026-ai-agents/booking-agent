"""v0.2 시연: 저장된 상태를 열어 읽는다 — 기억의 실체는 pg의 행이다.

두 겹으로 본다.
  1) SQL — checkpoint 테이블에 thread별로 행이 실제로 쌓여 있다
  2) graph.get_state() — 같은 데이터를 그래프의 눈으로 복원한 모습

demos/amnesia.py로 대화를 만든 뒤 실행하면 demo-amnesia thread가 보인다.
"""

import warnings

warnings.filterwarnings("ignore")   # upstream pending-deprecation 소음 차단 (수업 출력용)

import psycopg

from agent.graph import graph, pool
from agent.tools import DATABASE_URL

print("=== 1) SQL: checkpoint 테이블에 뭐가 쌓였나 ===\n")
with psycopg.connect(DATABASE_URL) as conn:
    tables = [r[0] for r in conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'checkpoint%' ORDER BY 1"
    ).fetchall()]
    print("checkpoint 테이블:", ", ".join(tables))
    rows = conn.execute(
        "SELECT thread_id, count(*) FROM checkpoints GROUP BY 1 ORDER BY 2 DESC LIMIT 5"
    ).fetchall()
    for thread_id, n in rows:
        print(f"  thread {thread_id!r}: checkpoint {n}개")

print("\n=== 2) graph.get_state(): 그래프의 눈으로 복원한 같은 데이터 ===\n")
state = graph.get_state({"configurable": {"thread_id": "demo-amnesia"}})
messages = state.values.get("messages", [])
print(f"demo-amnesia thread 메시지 {len(messages)}개:")
for m in messages:
    role = m.get("role")
    content = (m.get("content") or "(도구 호출)").replace("\n", " ")
    print(f"  [{role}] {content[:60]}{'…' if len(content) > 60 else ''}")

pool.close()   # 데모 프로세스는 여기서 끝 — 종료 경고 없이 닫는다
