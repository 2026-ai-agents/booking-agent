"""예약 상담 그래프 — v0.3: 쓰기 직전, 사람이 확인한다.

v0.2에서 상태가 pg로 이사했으니, 이제 그 위에 **human-in-the-loop**을
얹는다. advisor가 request_reservation(db에 쓰는 불가역 행위)을 요청하면
tools로 직행하지 않고 confirm 노드에서 interrupt()로 멈춘다. 손님이
승인하면 도구가 실행되고, 보류하면 도구는 실행되지 않은 채 거절 회신이
advisor로 돌아가 조건을 다시 묻는다.

멈춘 상태 자체가 checkpoint로 pg에 저장된다는 것이 핵심이다 — 확인
카드를 띄워 둔 채 서버를 재시작해도, 손님이 한참 뒤에 답해도, Command
(resume=…)가 그 자리에서 이어간다. 영속성(v0.2) 없이는 interrupt가 웹
제품이 될 수 없다.

읽기 도구(check_availability)는 확인 없이 지나간다. 되돌릴 수 없는
행위에만 사람을 세운다.
"""

import json
import operator
from datetime import date
from typing import Annotated, Literal, TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from litellm import completion
from psycopg_pool import ConnectionPool

from agent.config import pick_model
from agent.tools import DATABASE_URL, OPEN_SLOTS, run_tool, tool_schemas

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
- 예약 확인 질문("내 예약 어떻게 됐어요?")에는 my_reservations로 조회해
  상태(requested=승인 대기, confirmed=확정, declined=거절)를 알려준다.
- 취소 요청은 my_reservations로 대상을 확인한 뒤 cancel_reservation을 쓴다.
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


WRITE_TOOLS = {"request_reservation", "cancel_reservation"}   # 되돌릴 수 없는 도구 — 사람 확인을 거친다


def confirm(state: BookingState) -> dict:
    """쓰기 도구 앞의 관문: interrupt로 멈춰 손님의 최종 확인을 받는다.

    interrupt()는 여기서 실행을 멈추고 페이로드를 호출자에게 올려보낸다.
    Command(resume=결정)로 돌아오면 같은 자리에서 반환값으로 이어진다.
    """
    last = state["messages"][-1]
    write_calls = [c for c in last["tool_calls"] if c["function"]["name"] in WRITE_TOOLS]
    decision = interrupt({
        "type": "confirm_reservation",
        "requests": [json.loads(c["function"]["arguments"] or "{}") for c in write_calls],
    })
    if decision.get("approved"):
        return {"messages": []}          # 빈 델타 — 도구 실행(tools)으로 그대로 진행
    # 보류: 도구를 실행하지 않는다. 모든 tool_call에 회신은 해야 대화가 성립한다
    reason = decision.get("reason") or "손님이 확정을 보류했다"
    return {"messages": [
        {
            "role": "tool",
            "tool_call_id": c["id"],
            "content": json.dumps(
                {"declined_by_customer": True, "reason": reason,
                 "hint": "예약을 실행하지 않았다. 바뀐 조건을 물어보라."},
                ensure_ascii=False),
        }
        for c in last["tool_calls"]
    ]}


def route_after_advisor(state: BookingState) -> Literal["confirm", "tools", "__end__"]:
    last = state["messages"][-1]
    if not last.get("tool_calls"):
        return END
    names = {c["function"]["name"] for c in last["tool_calls"]}
    return "confirm" if names & WRITE_TOOLS else "tools"


def route_after_confirm(state: BookingState) -> Literal["tools", "advisor"]:
    """승인이면 빈 델타(마지막이 여전히 tool_calls) → tools로.
    보류면 거절 회신(tool 메시지)이 이미 붙었다 → advisor로."""
    return "advisor" if state["messages"][-1].get("role") == "tool" else "tools"


# ── 선언부 ────────────────────────────────────────────────────────────
builder = StateGraph(BookingState)
builder.add_node("advisor", advisor)
builder.add_node("tools", tools)
builder.add_node("confirm", confirm)
builder.add_edge(START, "advisor")
builder.add_conditional_edges("advisor", route_after_advisor,
                              {"confirm": "confirm", "tools": "tools", END: END})
builder.add_conditional_edges("confirm", route_after_confirm,
                              {"tools": "tools", "advisor": "advisor"})
builder.add_edge("tools", "advisor")

# v0.2: 상태의 거처가 pg로 옮겨진다. 이 세 줄이 재시작 생존의 전부다.
pool = ConnectionPool(DATABASE_URL, kwargs={"autocommit": True})
checkpointer = PostgresSaver(pool)
checkpointer.setup()   # checkpoint 테이블이 없으면 만든다 (멱등)

graph = builder.compile(checkpointer=checkpointer)
