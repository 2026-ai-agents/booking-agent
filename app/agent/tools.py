"""손님 예약 도구 — diet-agent와 같은 규약에 한 가지가 더해진다.

같은 것: pydantic 모델이 스키마와 검증을 겸하고, 실행은 run_tool 관문
하나로만 지나가며, 에러도 결과로 돌려준다.

더해진 것: **신원은 LLM의 인자가 아니다.** customer_id는 로그인에서 와서
그래프 상태가 나르고, tools 노드가 실행 시점에 주입한다. LLM이 "저는
3번 손님인데요"라는 말에 속아 남의 이름으로 예약하는 길을 스키마
수준에서 막는다.
"""

import json
import os
from datetime import date

import psycopg
from pydantic import BaseModel, Field, ValidationError

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://booking:booking@localhost:5432/bookingdb")

OPEN_SLOTS = ["11:00", "12:00", "13:00", "17:00", "18:00", "19:00", "20:00"]

# 슬롯을 점유하는 상태 — declined/cancelled 예약은 자리를 다시 내놓는다
OCCUPYING = ("requested", "confirmed")


class CheckAvailabilityArgs(BaseModel):
    """날짜·시간·인원에 앉을 수 있는 빈 테이블을 찾는다. 예약 전 반드시 호출."""

    res_date: date = Field(description="예약 날짜 (YYYY-MM-DD)")
    res_time: str = Field(description="예약 시간 — 정시 슬롯 (11:00, 12:00, 13:00, 17:00, 18:00, 19:00, 20:00)")
    party_size: int = Field(ge=1, le=12, description="인원 수")


def check_availability(args: CheckAvailabilityArgs, customer_id: int) -> dict:
    if args.res_time not in OPEN_SLOTS:
        return {"error": f"영업 슬롯이 아니다. 가능한 시간: {', '.join(OPEN_SLOTS)}"}
    with psycopg.connect(DATABASE_URL) as conn:
        rows = conn.execute(
            """SELECT t.name, t.capacity, t.location
               FROM dining_tables t
               WHERE t.capacity >= %s
                 AND NOT EXISTS (
                     SELECT 1 FROM reservations r
                     WHERE r.table_id = t.id AND r.res_date = %s
                       AND r.res_time = %s AND r.status = ANY(%s)
                 )
               ORDER BY t.capacity, t.name""",
            (args.party_size, args.res_date, args.res_time, list(OCCUPYING)),
        ).fetchall()
    return {
        "res_date": str(args.res_date),
        "res_time": args.res_time,
        "party_size": args.party_size,
        "tables": [{"name": r[0], "capacity": r[1], "location": r[2]} for r in rows],
    }


class RequestReservationArgs(BaseModel):
    """확인된 빈 테이블에 예약을 신청한다. 접수 후 사장 승인이 나야 확정이다."""

    table_name: str = Field(description="테이블 이름 (check_availability 결과에서 고른 것)")
    res_date: date = Field(description="예약 날짜 (YYYY-MM-DD)")
    res_time: str = Field(description="예약 시간 — 정시 슬롯")
    party_size: int = Field(ge=1, le=12, description="인원 수")
    note: str | None = Field(default=None, description="요청 사항 (없으면 생략)")


def request_reservation(args: RequestReservationArgs, customer_id: int) -> dict:
    if args.res_time not in OPEN_SLOTS:
        return {"error": f"영업 슬롯이 아니다. 가능한 시간: {', '.join(OPEN_SLOTS)}"}
    with psycopg.connect(DATABASE_URL) as conn:
        table = conn.execute(
            "SELECT id, capacity FROM dining_tables WHERE name = %s", (args.table_name,)
        ).fetchone()
        if table is None:
            return {"error": f"'{args.table_name}' 테이블이 없다. check_availability부터 다시."}
        table_id, capacity = table
        if capacity < args.party_size:
            return {"error": f"{args.table_name}은(는) {capacity}인석이라 {args.party_size}명이 못 앉는다."}
        taken = conn.execute(
            """SELECT 1 FROM reservations
               WHERE table_id = %s AND res_date = %s AND res_time = %s AND status = ANY(%s)""",
            (table_id, args.res_date, args.res_time, list(OCCUPYING)),
        ).fetchone()
        if taken:
            return {"error": f"{args.table_name}은(는) 그 시간에 이미 예약이 있다. 다른 테이블·시간을 안내하라."}
        row = conn.execute(
            """INSERT INTO reservations (customer_id, table_id, res_date, res_time, party_size, note)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (customer_id, table_id, args.res_date, args.res_time, args.party_size, args.note),
        ).fetchone()
        conn.commit()
    return {
        "reservation_id": row[0],
        "status": "requested",
        "summary": f"{args.res_date} {args.res_time} · {args.table_name} · {args.party_size}명",
        "notice": "접수되었다. 사장 승인이 나면 확정된다 — 손님에게 그렇게 안내하라.",
    }


class MyReservationsArgs(BaseModel):
    """이 손님의 예약 목록을 상태와 함께 조회한다 (오늘 이후)."""

    include_past: bool = Field(default=False, description="지난 예약도 포함할지")


def my_reservations(args: MyReservationsArgs, customer_id: int) -> dict:
    where = "" if args.include_past else "AND r.res_date >= CURRENT_DATE"
    with psycopg.connect(DATABASE_URL) as conn:
        rows = conn.execute(
            f"""SELECT r.id, r.res_date, r.res_time, t.name, r.party_size, r.status, r.note
                FROM reservations r JOIN dining_tables t ON t.id = r.table_id
                WHERE r.customer_id = %s {where}
                ORDER BY r.res_date, r.res_time""",
            (customer_id,),
        ).fetchall()
    return {"reservations": [
        {"reservation_id": r[0], "res_date": str(r[1]), "res_time": str(r[2])[:5],
         "table": r[3], "party_size": r[4], "status": r[5], "note": r[6]}
        for r in rows
    ]}


class CancelReservationArgs(BaseModel):
    """이 손님 본인의 예약을 취소한다. 취소 전 my_reservations로 id를 확인하라."""

    reservation_id: int = Field(description="취소할 예약 id (my_reservations 결과의 것)")


def cancel_reservation(args: CancelReservationArgs, customer_id: int) -> dict:
    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute(
            """UPDATE reservations SET status = 'cancelled'
               WHERE id = %s AND customer_id = %s AND status IN ('requested', 'confirmed')
               RETURNING id""",
            (args.reservation_id, customer_id),
        ).fetchone()
        conn.commit()
    if row is None:
        return {"error": "취소할 수 없다 — 본인 예약이 아니거나 이미 취소/거절된 건이다."}
    return {"reservation_id": row[0], "status": "cancelled"}


REGISTRY: dict[str, tuple[type[BaseModel], object]] = {
    "check_availability": (CheckAvailabilityArgs, check_availability),
    "request_reservation": (RequestReservationArgs, request_reservation),
    "my_reservations": (MyReservationsArgs, my_reservations),
    "cancel_reservation": (CancelReservationArgs, cancel_reservation),
}


def tool_schemas() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": (model.__doc__ or "").strip(),
                "parameters": model.model_json_schema(),
            },
        }
        for name, (model, _fn) in REGISTRY.items()
    ]


def run_tool(name: str, raw_arguments: str, customer_id: int) -> str:
    entry = REGISTRY.get(name)
    if entry is None:
        return json.dumps({"error": f"없는 도구: {name}"}, ensure_ascii=False)
    args_model, fn = entry
    try:
        args = args_model.model_validate(json.loads(raw_arguments or "{}"))
    except (ValidationError, json.JSONDecodeError) as e:
        return json.dumps({"error": f"인자 검증 실패: {e}"}, ensure_ascii=False)
    return json.dumps(fn(args, customer_id), ensure_ascii=False, default=str)
