"""사장 어시스턴트 그래프 — 조회 전용이라 confirm 관문이 없다.

한 앱에 그래프가 둘이다: 손님 그래프(graph.py)는 쓰기 앞에 interrupt가
서고, 이 그래프는 읽기만 하므로 advisor ↔ tools 순환이 전부다. 같은
PostgresSaver를 나눠 쓰므로 사장의 상담 thread도 재시작을 넘어 이어진다.

승인/거절의 실행은 관리자 화면의 버튼(/admin/decide)이 맡는다 — 예약
상태를 바꾸는 손은 사람에게 남겨 둔다.
"""

import operator
from datetime import date
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from litellm import completion

from agent.admin_tools import run_admin_tool, tool_schemas
from agent.config import pick_model
from agent.graph import checkpointer

ADMIN_SYSTEM_PROMPT = """당신은 한식당 '소나무' 사장의 운영 어시스턴트다. 예약 현황을
조회하고 집계해 보고한다.

## 도구 사용
- 목록·현황 질문은 고정 도구(list_reservations, reservation_stats)를 먼저 쓴다.
- 고정 도구로 답할 수 없는 집계·탐색 질문만 run_sql로 SELECT를 작성해 조회한다.
  run_sql 결과를 보고할 때는 어떤 쿼리를 썼는지 한 줄로 밝힌다.
- 승인/거절의 실행은 화면의 버튼이 맡는다. 당신은 조회와 보고까지만 한다.
- 수치는 지어내지 않는다. 반드시 도구로 확인한 값만 말한다.
- 오늘은 {today}다.

답은 간결한 한국어로, 표가 어울리면 표로."""


class AdminState(TypedDict):
    messages: Annotated[list[dict], operator.add]


def advisor(state: AdminState) -> dict:
    response = completion(
        model=pick_model(),
        messages=[
            {"role": "system", "content": ADMIN_SYSTEM_PROMPT.format(today=date.today().isoformat())},
            *state["messages"],
        ],
        tools=tool_schemas(),
    )
    return {"messages": [response.choices[0].message.model_dump()]}


def tools(state: AdminState) -> dict:
    last = state["messages"][-1]
    return {
        "messages": [
            {
                "role": "tool",
                "tool_call_id": call["id"],
                "content": run_admin_tool(call["function"]["name"], call["function"]["arguments"]),
            }
            for call in last["tool_calls"]
        ]
    }


def route_after_advisor(state: AdminState) -> Literal["tools", "__end__"]:
    last = state["messages"][-1]
    return "tools" if last.get("tool_calls") else END


builder = StateGraph(AdminState)
builder.add_node("advisor", advisor)
builder.add_node("tools", tools)
builder.add_edge(START, "advisor")
builder.add_conditional_edges("advisor", route_after_advisor, {"tools": "tools", END: END})
builder.add_edge("tools", "advisor")

admin_graph = builder.compile(checkpointer=checkpointer)   # 손님 그래프와 같은 pg checkpointer
