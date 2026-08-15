"""v0.2의 약속을 박제한다: 상태는 pg에 있고, 프로세스는 갈아끼워도 된다."""

import uuid

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver

from agent import graph as graph_module
from agent.tools import DATABASE_URL
from tests.conftest import ScriptedLLM, fake_response


def wire(monkeypatch, responses):
    llm = ScriptedLLM(responses)
    monkeypatch.setattr(graph_module, "completion", llm)
    return llm


def state(message: str) -> dict:
    return {
        "messages": [{"role": "user", "content": message}],
        "customer_id": 1,
        "customer_name": "김서연",
    }


def test_fresh_graph_instance_resumes_thread(monkeypatch):
    """재시작 생존의 유닛테스트 판: 새로 compile한 그래프가 대화를 이어받는다."""
    llm = wire(monkeypatch, [
        fake_response(content="6명 모임이시군요. 언제가 좋으세요?"),
        fake_response(content="네, 6명이라고 하셨습니다."),
    ])
    config = {"configurable": {"thread_id": f"t-{uuid.uuid4().hex[:8]}"}}
    graph_module.graph.invoke(state("6명 모임 예약요"), config)

    # 새 프로세스 흉내: 같은 pool 위에 새 saver·새 compile — 메모리 공유가 없다
    fresh = graph_module.builder.compile(
        checkpointer=PostgresSaver(graph_module.pool)
    )
    fresh.invoke(state("몇 명이라고 했죠?"), config)
    sent = llm.calls[1]["messages"]
    assert [m.get("role") for m in sent] == ["system", "user", "assistant", "user"]


def test_checkpoints_are_rows_in_pg(monkeypatch):
    wire(monkeypatch, [fake_response(content="안녕하세요!")])
    thread = f"t-{uuid.uuid4().hex[:8]}"
    graph_module.graph.invoke(state("안녕하세요"), {"configurable": {"thread_id": thread}})
    with psycopg.connect(DATABASE_URL) as conn:
        n = conn.execute(
            "SELECT count(*) FROM checkpoints WHERE thread_id = %s", (thread,)
        ).fetchone()[0]
    assert n > 0
