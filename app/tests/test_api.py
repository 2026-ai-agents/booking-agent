"""로그인은 인증이 아니라 식별이다 — 같은 전화는 언제나 같은 손님."""

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health():
    body = client.get("/health").json()
    assert body["ok"] is True


def test_login_same_phone_same_customer():
    first = client.post("/login", json={"name": "테스트", "phone": "010-9999-0001"}).json()
    second = client.post("/login", json={"name": "테스트2", "phone": "010-9999-0001"}).json()
    assert first["customer_id"] == second["customer_id"]
    assert second["name"] == "테스트2"          # 이름은 최신으로 갱신된다
    assert second["thread_id"] == f"cust-{second['customer_id']}"
