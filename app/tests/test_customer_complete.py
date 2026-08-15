"""v1.0 손님 완성분: 조회는 자유, 취소는 확인을 거치고 본인 것만 된다."""

import json
import uuid

import psycopg
import pytest
from langgraph.types import Command

from agent import graph as graph_module
from agent import tools
from agent.tools import DATABASE_URL
from tests.conftest import ScriptedLLM, fake_response, fake_tool_call


@pytest.fixture(autouse=True)
def clean_far_future():
    yield
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute("DELETE FROM reservations WHERE res_date >= '2099-01-01'")
        conn.commit()


def seed_reservation(customer_id: int) -> int:
    with psycopg.connect(DATABASE_URL) as conn:
        rid = conn.execute(
            """INSERT INTO reservations (customer_id, table_id, res_date, res_time, party_size)
               VALUES (%s, (SELECT id FROM dining_tables WHERE name = '홀3'),
                       '2099-12-30', '18:00', 4) RETURNING id""",
            (customer_id,),
        ).fetchone()[0]
        conn.commit()
    return rid


def wire(monkeypatch, responses):
    llm = ScriptedLLM(responses)
    monkeypatch.setattr(graph_module, "completion", llm)
    return llm


def cfg():
    return {"configurable": {"thread_id": f"t-{uuid.uuid4().hex[:8]}"}}


def state(message: str, customer_id: int = 1) -> dict:
    return {
        "messages": [{"role": "user", "content": message}],
        "customer_id": customer_id,
        "customer_name": "김서연",
    }


def test_my_reservations_lists_own_rows():
    rid = seed_reservation(customer_id=1)
    result = json.loads(tools.run_tool("my_reservations", "{}", customer_id=1))
    ids = [r["reservation_id"] for r in result["reservations"]]
    assert rid in ids
    other = json.loads(tools.run_tool("my_reservations", "{}", customer_id=2))
    assert rid not in [r["reservation_id"] for r in other["reservations"]]


def test_cancel_goes_through_confirmation(monkeypatch):
    rid = seed_reservation(customer_id=1)
    wire(monkeypatch, [
        fake_response(tool_calls=[fake_tool_call("cancel_reservation", f'{{"reservation_id": {rid}}}')]),
        fake_response(content="취소했습니다."),
    ])
    config = cfg()
    result = graph_module.graph.invoke(state("그 예약 취소해 주세요"), config)
    assert "__interrupt__" in result       # 취소도 쓰기 — 확인 카드가 선다
    graph_module.graph.invoke(Command(resume={"approved": True}), config)
    with psycopg.connect(DATABASE_URL) as conn:
        status = conn.execute(
            "SELECT status FROM reservations WHERE id = %s", (rid,)
        ).fetchone()[0]
    assert status == "cancelled"


def test_cancel_rejects_someone_elses_reservation(monkeypatch):
    rid = seed_reservation(customer_id=1)     # 김서연의 예약을
    wire(monkeypatch, [
        fake_response(tool_calls=[fake_tool_call("cancel_reservation", f'{{"reservation_id": {rid}}}')]),
        fake_response(content="취소할 수 없었습니다."),
    ])
    config = cfg()
    graph_module.graph.invoke(state("예약 취소요", customer_id=2), config)   # 박지훈이 시도
    result = graph_module.graph.invoke(Command(resume={"approved": True}), config)
    tool_msg = [m for m in result["messages"] if m.get("role") == "tool"][0]
    assert "error" in json.loads(tool_msg["content"])
    with psycopg.connect(DATABASE_URL) as conn:
        status = conn.execute(
            "SELECT status FROM reservations WHERE id = %s", (rid,)
        ).fetchone()[0]
    assert status == "requested"              # 남의 예약은 그대로다
