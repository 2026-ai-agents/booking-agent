"""v1.1의 약속: 전화는 모양이 달라도 같은 손님, 대화는 화면이 닫혀도 복원된다."""

import uuid

from fastapi.testclient import TestClient

from agent import graph as graph_module
from main import app
from tests.conftest import ScriptedLLM, fake_response

client = TestClient(app)


def test_phone_formats_are_same_customer():
    first = client.post("/login", json={"name": "테스트", "phone": "010-9999-0002"}).json()
    second = client.post("/login", json={"name": "테스트", "phone": "01099990002"}).json()
    third = client.post("/login", json={"name": "테스트", "phone": "010 9999 0002"}).json()
    assert first["customer_id"] == second["customer_id"] == third["customer_id"]


def test_history_restores_conversation(monkeypatch):
    llm = ScriptedLLM([fake_response(content="언제 오시나요?")])
    monkeypatch.setattr(graph_module, "completion", llm)
    thread = f"t-{uuid.uuid4().hex[:8]}"
    client.post("/chat", json={"customer_id": 1, "customer_name": "김서연",
                               "thread_id": thread, "message": "예약하고 싶어요"})
    restored = client.get(f"/history/{thread}").json()
    assert [(m["role"], m["content"]) for m in restored["messages"]] == [
        ("user", "예약하고 싶어요"),
        ("assistant", "언제 오시나요?"),
    ]
    assert restored["interrupt"] is None


def test_history_restores_pending_confirm_card(monkeypatch):
    from tests.conftest import fake_tool_call
    llm = ScriptedLLM([fake_response(tool_calls=[fake_tool_call(
        "request_reservation",
        '{"table_name": "홀2", "res_date": "2099-12-28", "res_time": "18:00", "party_size": 4}',
    )])])
    monkeypatch.setattr(graph_module, "completion", llm)
    thread = f"t-{uuid.uuid4().hex[:8]}"
    client.post("/chat", json={"customer_id": 1, "customer_name": "김서연",
                               "thread_id": thread, "message": "홀2 예약요"})
    # 화면을 닫고 다시 로그인한 상황 — 열려 있던 확인 카드가 그대로 온다
    restored = client.get(f"/history/{thread}").json()
    assert restored["interrupt"]["type"] == "confirm_reservation"
    assert restored["interrupt"]["requests"][0]["table_name"] == "홀2"


def test_empty_thread_restores_nothing():
    restored = client.get(f"/history/never-{uuid.uuid4().hex[:6]}").json()
    assert restored == {"messages": [], "interrupt": None}
