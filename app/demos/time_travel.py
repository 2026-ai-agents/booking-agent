"""v1.0 시연: time-travel — "다른 시간대로 예약했다면"을 과거에서 다시 산다.

checkpointer는 최신 상태만 저장하는 게 아니라 **모든 단계의 상태**를
남긴다. get_state_history로 그 목록을 열고, 확인 카드 직전의 checkpoint를
골라 거기서 다시 실행하면(포크), 같은 대화가 다른 결정으로 갈라진다.
원래 계보는 그대로 남는다 — 되돌리기가 아니라 평행 재생이다.

흐름 (LLM 실제 호출, thread는 매번 새로):
  1) 예약 대화를 확인 카드까지 진행하고 승인 → 접수 (원래 계보)
  2) history에서 confirm 직전 checkpoint를 찾는다
  3) 그 checkpoint에서 재실행 → 확인 카드가 다시 선다 (포크)
  4) 이번엔 보류 + "한 시간 늦게" → 상담사가 새 시간으로 다시 확인을 청한다
"""

import uuid
import warnings

warnings.filterwarnings("ignore")   # upstream pending-deprecation 소음 차단 (수업 출력용)

from langgraph.types import Command

from agent.graph import graph, pool

CONFIG = {"configurable": {"thread_id": f"demo-tt-{uuid.uuid4().hex[:6]}"}}


def show(tag: str, result: dict) -> None:
    if "__interrupt__" in result:
        print(f"[{tag}] 확인 카드: {result['__interrupt__'][0].value['requests']}")
    else:
        print(f"[{tag}] {result['messages'][-1]['content'][:80]}…")


state = {
    "messages": [{"role": "user", "content":
                  "다음 주 수요일 19:00에 4명, 홀 테이블로 예약해 주세요. 되는 테이블 아무거나요."}],
    "customer_id": 1, "customer_name": "김서연",
}
result = graph.invoke(state, CONFIG)
show("1턴", result)
result = graph.invoke(Command(resume={"approved": True}), CONFIG)
show("승인", result)

history = list(graph.get_state_history(CONFIG))
print(f"\nhistory: checkpoint {len(history)}개가 pg에 남아 있다")
past = next(s for s in history if s.next == ("confirm",))
print(f"confirm 직전 checkpoint를 찾았다: {past.config['configurable']['checkpoint_id'][:8]}…\n")

print("=== 그 시점에서 다시 실행한다 (포크) ===")
forked = graph.invoke(None, past.config)
show("포크", forked)

print("\n=== 이번엔 다른 결정을 내린다: 보류 + 한 시간 늦게 ===")
redo = graph.invoke(Command(resume={"approved": False, "reason": "한 시간 늦은 20:00로 바꿔줘"}),
                    CONFIG)
show("재결정", redo)

after = len(list(graph.get_state_history(CONFIG)))
print(f"\nhistory: {len(history)}개 → {after}개 — 원래 계보 위에 평행 계보가 얹혔다")
pool.close()
