"""사장 입장의 약속: SQL 도구는 세 겹 방어를 지키고, 승인은 상태 머신이다."""

import json

import psycopg
import pytest
from fastapi.testclient import TestClient

from agent import admin_tools
from agent.tools import DATABASE_URL
from main import app

client = TestClient(app)
ADMIN = {"x-admin-password": "changeme"}


@pytest.fixture(autouse=True)
def clean_far_future():
    yield
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute("DELETE FROM reservations WHERE res_date >= '2099-01-01'")
        conn.commit()


def sql(query: str) -> dict:
    return json.loads(admin_tools.run_admin_tool("run_sql", json.dumps({"query": query})))


# ── run_sql: 세 겹 방어 ──────────────────────────────────────────────

def test_sql_select_works_and_gets_auto_limit():
    result = sql("SELECT name, capacity FROM dining_tables ORDER BY capacity DESC")
    assert result["columns"] == ["name", "capacity"]
    assert result["rows"][0][0] == "룸2"
    assert result["query"].endswith("LIMIT 50")      # 1겹: LIMIT 자동 부착


def test_sql_rejects_non_select():
    for query in ("DELETE FROM reservations", "UPDATE reservations SET status='confirmed'",
                  "DROP TABLE reservations", "WITH x AS (SELECT 1) SELECT * FROM x"):
        assert "error" in sql(query)                  # 2겹: SELECT 한정


def test_sql_rejects_multi_statement():
    assert "error" in sql("SELECT 1; DELETE FROM reservations")


def test_sql_readonly_transaction_blocks_sneaky_writes():
    # 검사문(SELECT 시작)을 통과하는 진짜 쓰기(setval)도 pg가 거부한다 — 3겹
    result = sql("SELECT setval('reservations_id_seq', 999999)")
    assert "error" in result
    assert "read-only" in result["error"]


# ── 고정 도구 ────────────────────────────────────────────────────────

def test_stats_counts_by_status():
    result = json.loads(admin_tools.run_admin_tool("reservation_stats", "{}"))
    assert "by_status" in result and "by_date" in result


# ── /admin API: 간이 인증 + 상태 머신 ────────────────────────────────

def test_admin_requires_password():
    assert client.get("/admin/reservations").status_code == 401        # 아무 인증도 없음
    assert client.get("/admin/reservations",
                      headers={"x-admin-password": "wrong"}).status_code == 401


def test_admin_login_issues_working_token():
    assert client.post("/admin/login", json={"password": "wrong"}).status_code == 401
    token = client.post("/admin/login", json={"password": "changeme"}).json()["token"]
    assert client.get("/admin/reservations",
                      headers={"x-admin-token": token}).status_code == 200
    assert client.get("/admin/reservations",
                      headers={"x-admin-token": "bogus"}).status_code == 401


def make_requested() -> int:
    with psycopg.connect(DATABASE_URL) as conn:
        rid = conn.execute(
            """INSERT INTO reservations (customer_id, table_id, res_date, res_time, party_size)
               VALUES (1, (SELECT id FROM dining_tables WHERE name = '창가2'),
                       '2099-12-29', '11:00', 2) RETURNING id""",
        ).fetchone()[0]
        conn.commit()
    return rid


def test_decide_flips_requested_to_confirmed_once():
    rid = make_requested()
    first = client.post("/admin/decide", headers=ADMIN,
                        json={"reservation_id": rid, "approved": True})
    assert first.json() == {"reservation_id": rid, "status": "confirmed"}
    with psycopg.connect(DATABASE_URL) as conn:
        decided_at = conn.execute(
            "SELECT decided_at FROM reservations WHERE id = %s", (rid,)
        ).fetchone()[0]
    assert decided_at is not None
    # 이미 결정된 건은 다시 못 바꾼다 — requested에서만 전이
    second = client.post("/admin/decide", headers=ADMIN,
                         json={"reservation_id": rid, "approved": False})
    assert second.status_code == 409


def test_decline_marks_declined():
    rid = make_requested()
    result = client.post("/admin/decide", headers=ADMIN,
                         json={"reservation_id": rid, "approved": False})
    assert result.json()["status"] == "declined"
