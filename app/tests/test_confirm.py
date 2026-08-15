"""v0.3의 약속을 박제한다: 쓰기는 확인 전엔 일어나지 않고, 결정으로 갈린다."""

import json
import uuid

import psycopg
import pytest
from langgraph.types import Command

from agent import graph as graph_module
from agent.tools import DATABASE_URL
from tests.conftest import ScriptedLLM, fake_response, fake_tool_call

RESERVE_CALL = fake_tool_call(
    "request_reservation",
    '{"table_name": "홀2", "res_date": "2099-12-31", "res_time": "19:00", "party_size": 4}',
)


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
        "customer_id": 1,
        "customer_name": "김서연",
    }


def rows() -> int:
    with psycopg.connect(DATABASE_URL) as conn:
        return conn.execute(
            "SELECT count(*) FROM reservations WHERE res_date >= '2099-01-01'"
        ).fetchone()[0]


def test_write_tool_pauses_before_execution(monkeypatch):
    wire(monkeypatch, [fake_response(tool_calls=[RESERVE_CALL])])
    result = graph_module.graph.invoke(state("홀2로 예약해 주세요"), cfg())
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["type"] == "confirm_reservation"
    assert payload["requests"][0]["table_name"] == "홀2"
    assert rows() == 0                     # 멈춘 동안 db에는 아무것도 없다


def test_approve_executes_the_write(monkeypatch):
    wire(monkeypatch, [
        fake_response(tool_calls=[RESERVE_CALL]),
        fake_response(content="접수되었습니다. 사장님 승인 후 확정됩니다."),
    ])
    config = cfg()
    graph_module.graph.invoke(state("홀2로 예약해 주세요"), config)
    result = graph_module.graph.invoke(Command(resume={"approved": True}), config)
    assert rows() == 1
    tool_msg = [m for m in result["messages"] if m.get("role") == "tool"][0]
    assert json.loads(tool_msg["content"])["status"] == "requested"


def test_decline_skips_the_write(monkeypatch):
    wire(monkeypatch, [
        fake_response(tool_calls=[RESERVE_CALL]),
        fake_response(content="알겠습니다. 어떤 조건으로 바꿀까요?"),
    ])
    config = cfg()
    graph_module.graph.invoke(state("홀2로 예약해 주세요"), config)
    result = graph_module.graph.invoke(
        Command(resume={"approved": False, "reason": "시간을 바꾸고 싶다"}), config
    )
    assert rows() == 0                     # 도구는 실행되지 않았다
    tool_msg = [m for m in result["messages"] if m.get("role") == "tool"][0]
    assert json.loads(tool_msg["content"])["declined_by_customer"] is True


def test_read_tool_passes_without_confirmation(monkeypatch):
    wire(monkeypatch, [
        fake_response(tool_calls=[fake_tool_call(
            "check_availability",
            '{"res_date": "2099-12-31", "res_time": "19:00", "party_size": 4}',
        )]),
        fake_response(content="홀2 등 자리가 있습니다."),
    ])
    result = graph_module.graph.invoke(state("모레 저녁 자리 있어요?"), cfg())
    assert "__interrupt__" not in result   # 읽기는 멈추지 않는다
    assert result["messages"][-1]["content"].endswith("있습니다.")
