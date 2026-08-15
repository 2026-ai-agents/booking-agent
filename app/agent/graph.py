"""예약 상담 그래프 — v0.1: 대화는 되지만, 기억은 프로세스 메모리에 산다.

diet-agent에서 완성한 모양(advisor ↔ tools 순환 + reducer + checkpointer)을
그대로 딛고 시작한다. 이 저장소가 새로 얹는 것은 그래프 모양이 아니라
**그 상태가 어디 사는가**다. v0.1의 MemorySaver는 프로세스 메모리라
`docker compose restart app` 한 방에 모든 대화가 사라진다 — 이 결핍을
겪는 것이 v0.1의 목적이고, v0.2가 PostgreSQL로 답한다.

diet-agent와 다른 점 하나: 상태에 customer_id가 실린다. 로그인에서 온
신원을 그래프가 나르고, tools 노드가 도구 실행에 주입한다.
"""

import operator
from datetime import date
from typing import Annotated, Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from litellm import completion

from agent.config import pick_model
from agent.tools import OPEN_SLOTS, run_tool, tool_schemas

SYSTEM_PROMPT = """당신은 한식당 '소나무'의 예약 상담사다. 손님과 대화하며 예약을 잡는다.

## 식당 규칙
- 영업 슬롯(정시): {slots}. 한 팀이 한 슬롯을 쓴다.
- 좌석: 창가(2인석), 홀(4~6인석), 룸(6~10인석)

## 진행 방법
- 날짜·시간·인원이 다 모이면 반드시 check_availability로 빈 테이블을 확인한다.
  가용 여부를 지어내지 않는다.
- 손님이 테이블을 고르면 request_reservation으로 신청을 접수한다.
- 접수는 확정이 아니다. "사장님 승인 후 확정되며, 결과는 이 대화에서
  확인할 수 있다"고 안내한다.
- 오늘은 {today}다. "내일", "모레" 같은 상대 날짜는 이 기준으로 계산한다.

답은 간결하게 한국어로. 손님 이름({customer_name} 님)을 자연스럽게 부른다."""


class BookingState(TypedDict):
    """messages에는 reducer가 붙고(델타 반환), 신원 두 칸은 매 호출 덮어쓴다."""

    messages: Annotated[list[dict], operator.add]
    customer_id: int
    customer_name: str


def advisor(state: BookingState) -> dict:
    system = SYSTEM_PROMPT.format(
        slots=", ".join(OPEN_SLOTS),
        today=date.today().isoformat(),
        customer_name=state.get("customer_name", "손님"),
    )
    response = completion(
        model=pick_model(),
        messages=[{"role": "system", "content": system}, *state["messages"]],
        tools=tool_schemas(),
    )
    return {"messages": [response.choices[0].message.model_dump()]}


def tools(state: BookingState) -> dict:
    """요청된 도구를 전부 실행한다. customer_id는 상태에서 주입 — LLM 인자가 아니다."""
    last = state["messages"][-1]
    return {
        "messages": [
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": run_tool(
                    call["function"]["name"],
                    call["function"]["arguments"],
                    customer_id=state["customer_id"],
                ),
            }
            for call in last["tool_calls"]
        ]
    }


def route_after_advisor(state: BookingState) -> Literal["tools", "__end__"]:
    last = state["messages"][-1]
    return "tools" if last.get("tool_calls") else END


# ── 선언부 ────────────────────────────────────────────────────────────
builder = StateGraph(BookingState)
builder.add_node("advisor", advisor)
builder.add_node("tools", tools)
builder.add_edge(START, "advisor")
builder.add_conditional_edges("advisor", route_after_advisor, {"tools": "tools", END: END})
builder.add_edge("tools", "advisor")

# v0.1의 결핍: MemorySaver는 프로세스 메모리다. 재시작하면 모든 thread가 증발한다.
graph = builder.compile(checkpointer=MemorySaver())
