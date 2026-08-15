"""그래프 경로와 신원 주입을 각본 LLM으로 검증한다. 도구가 때리는 db는 진짜다."""

import json
import uuid

import psycopg
import pytest
from langgraph.types import Command

from agent import graph as graph_module
from agent.tools import DATABASE_URL
from tests.conftest import ScriptedLLM, fake_response, fake_tool_call


@pytest.fixture(autouse=True)
def clean_far_future():
    yield
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute("DELETE FROM reservations WHERE res_date >= '2099-01-01'")
        conn.commit()


def wire(monkeypatch, responses):
    llm = ScriptedLLM(responses)
    monkeypatch.setattr(graph_module, "completion", llm)
    return llm


def cfg():
    return {"configurable": {"thread_id": f"t-{uuid.uuid4().hex[:8]}"}}


def state(message: str) -> dict:
    return {
        "messages": [{"role": "user", "content": message}],
        "customer_id": 2,
        "customer_name": "박지훈",
    }


def test_direct_answer_skips_tools(monkeypatch):
    llm = wire(monkeypatch, [fake_response(content="날짜와 인원을 알려 주세요.")])
    result = graph_module.graph.invoke(state("예약하고 싶어요"), cfg())
    assert result["messages"][-1]["content"] == "날짜와 인원을 알려 주세요."
    assert len(llm.calls) == 1


def test_tool_roundtrip_injects_identity(monkeypatch):
    wire(monkeypatch, [
        fake_response(tool_calls=[fake_tool_call(
            "request_reservation",
            '{"table_name": "홀3", "res_date": "2099-12-31", "res_time": "17:00", "party_size": 5}',
        )]),
        fake_response(content="접수되었습니다. 사장님 승인 후 확정됩니다."),
    ])
    config = cfg()
    graph_module.graph.invoke(state("모레 5시에 5명요"), config)
    # v0.3부터 쓰기는 확인을 거친다 — 승인해야 도구가 실행된다
    result = graph_module.graph.invoke(Command(resume={"approved": True}), config)
    tool_msg = [m for m in result["messages"] if m.get("role") == "tool"][0]
    reservation_id = json.loads(tool_msg["content"])["reservation_id"]
    with psycopg.connect(DATABASE_URL) as conn:
        owner = conn.execute(
            "SELECT customer_id FROM reservations WHERE id = %s", (reservation_id,)
        ).fetchone()[0]
    # 예약 소유자는 상태의 customer_id — LLM은 신원 인자를 만들 수 없다
    assert owner == 2


def test_same_thread_remembers(monkeypatch):
    llm = wire(monkeypatch, [
        fake_response(content="내일 몇 시가 좋으세요?"),
        fake_response(content="4명, 내일 저녁으로 찾아볼게요."),
    ])
    config = cfg()
    graph_module.graph.invoke(state("내일 예약요"), config)
    graph_module.graph.invoke(state("4명이에요"), config)
    sent = llm.calls[1]["messages"]
    assert [m.get("role") for m in sent] == ["system", "user", "assistant", "user"]
