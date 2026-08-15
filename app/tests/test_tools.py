"""도구는 진짜 db를 때린다 — 시드와 슬롯 점유 규칙을 그대로 검증한다."""

import json
from datetime import date, timedelta

import psycopg
import pytest

from agent import tools
from agent.tools import DATABASE_URL

TOMORROW = (date.today() + timedelta(days=1)).isoformat()
FAR = "2099-12-31"  # 쓰기 테스트 전용 날짜 — 시드·다른 테스트와 안 겹친다


@pytest.fixture(autouse=True)
def clean_far_future():
    yield
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute("DELETE FROM reservations WHERE res_date >= '2099-01-01'")
        conn.commit()


def run(name, **kwargs):
    return json.loads(tools.run_tool(name, json.dumps(kwargs, default=str), customer_id=1))


def test_availability_respects_seed_occupancy():
    # 시드: 내일 18:00 홀1(4인석)은 confirmed로 차 있다
    result = run("check_availability", res_date=TOMORROW, res_time="18:00", party_size=4)
    names = [t["name"] for t in result["tables"]]
    assert "홀1" not in names
    assert "홀2" in names          # 같은 4인석인데 비어 있다
    assert "창가1" not in names    # 2인석은 4명이 못 앉는다


def test_availability_rejects_non_slot_time():
    result = run("check_availability", res_date=TOMORROW, res_time="15:30", party_size=2)
    assert "error" in result


def test_request_writes_requested_row():
    result = run("request_reservation", table_name="홀2", res_date=FAR,
                 res_time="18:00", party_size=4, note="창가 쪽이면 좋아요")
    assert result["status"] == "requested"
    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute(
            "SELECT customer_id, status, note FROM reservations WHERE id = %s",
            (result["reservation_id"],),
        ).fetchone()
    # 신원은 run_tool 주입값 — LLM 인자가 아니다
    assert row == (1, "requested", "창가 쪽이면 좋아요")


def test_request_rejects_taken_slot():
    first = run("request_reservation", table_name="룸1", res_date=FAR, res_time="19:00", party_size=6)
    assert first["status"] == "requested"
    second = run("request_reservation", table_name="룸1", res_date=FAR, res_time="19:00", party_size=6)
    assert "error" in second


def test_request_rejects_oversize_party():
    result = run("request_reservation", table_name="창가1", res_date=FAR, res_time="11:00", party_size=4)
    assert "error" in result
