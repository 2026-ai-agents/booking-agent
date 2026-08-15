"""예약 상담 그래프 — v0.2: 기억이 PostgreSQL로 이사한다.

v0.1과 그래프 모양은 완전히 같다. 바뀐 것은 **상태의 거처** 하나다:
MemorySaver(프로세스 메모리) → PostgresSaver(db 컨테이너). checkpoint가
pg 테이블에 쌓이므로 `docker compose restart app`을 해도, app 컨테이너를
지웠다 새로 만들어도, 같은 thread_id로 돌아오면 대화가 이어진다.

setup()은 checkpoint 테이블 4개(checkpoints, checkpoint_writes,
checkpoint_blobs, checkpoint_migrations)를 처음 한 번 만든다 — 도메인
스키마(db/init)와 같은 db에 살아서, 시연 때 SQL로 열어 읽을 수 있다.

diet-agent와 다른 점 하나: 상태에 customer_id가 실린다. 로그인에서 온
신원을 그래프가 나르고, tools 노드가 도구 실행에 주입한다.
"""

import operator
from datetime import date
from typing import Annotated, Literal, TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
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

# v0.2: 상태의 거처가 pg로 옮겨진다. 이 세 줄이 재시작 생존의 전부다.
pool = ConnectionPool(DATABASE_URL, kwargs={"autocommit": True})
checkpointer = PostgresSaver(pool)
checkpointer.setup()   # checkpoint 테이블이 없으면 만든다 (멱등)

graph = builder.compile(checkpointer=checkpointer)
