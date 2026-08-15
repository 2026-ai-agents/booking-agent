"""사장 어시스턴트의 도구 — 고정 도구 둘, 자유 쿼리 하나.

고정 도구(list_reservations, reservation_stats)는 안전하지만 정해진
질문만 답한다. run_sql은 LLM이 SELECT를 직접 작성해 어떤 집계든 하지만,
그만큼 위험해서 세 겹의 방어를 두른다:

  1) SELECT 한 문장만 통과 (다른 시작·다중 문장 거부)
  2) 트랜잭션을 READ ONLY로 강제 — 검사문을 뚫는 쓰기도 pg가 거부한다
  3) LIMIT이 없으면 LIMIT 50을 붙인다 — 폭주 조회 방지

도구 설계의 스펙트럼(고정 vs 자유)과 그 대가(방어)를 보이는 것이 목적이다.
"""

import json

import psycopg
from pydantic import BaseModel, Field, ValidationError

from agent.tools import DATABASE_URL

STATUSES = ("requested", "confirmed", "declined", "cancelled")


class ListReservationsArgs(BaseModel):
    """예약 목록을 조회한다. 기본은 오늘 이후 전부, status로 거를 수 있다."""

    status: str | None = Field(default=None, description="requested/confirmed/declined/cancelled 중 하나")
    include_past: bool = Field(default=False, description="지난 예약도 포함할지")


def list_reservations(args: ListReservationsArgs) -> dict:
    if args.status is not None and args.status not in STATUSES:
        return {"error": f"status는 {', '.join(STATUSES)} 중 하나여야 한다."}
    clauses, params = [], []
    if not args.include_past:
        clauses.append("r.res_date >= CURRENT_DATE")
    if args.status:
        clauses.append("r.status = %s")
        params.append(args.status)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with psycopg.connect(DATABASE_URL) as conn:
        rows = conn.execute(
            f"""SELECT r.id, r.res_date, r.res_time, t.name, c.name, r.party_size, r.status, r.note
                FROM reservations r
                JOIN dining_tables t ON t.id = r.table_id
                JOIN customers c ON c.id = r.customer_id
                {where} ORDER BY r.res_date, r.res_time LIMIT 50""",
            params,
        ).fetchall()
    return {"reservations": [
        {"reservation_id": r[0], "res_date": str(r[1]), "res_time": str(r[2])[:5],
         "table": r[3], "customer": r[4], "party_size": r[5], "status": r[6], "note": r[7]}
        for r in rows
    ]}


class ReservationStatsArgs(BaseModel):
    """오늘 이후 예약을 상태별·날짜별로 집계한다."""

    days: int = Field(default=7, ge=1, le=31, description="오늘부터 며칠치")


def reservation_stats(args: ReservationStatsArgs) -> dict:
    with psycopg.connect(DATABASE_URL) as conn:
        by_status = conn.execute(
            """SELECT status, count(*) FROM reservations
               WHERE res_date BETWEEN CURRENT_DATE AND CURRENT_DATE + %s
               GROUP BY status ORDER BY status""",
            (args.days,),
        ).fetchall()
        by_date = conn.execute(
            """SELECT res_date, count(*), sum(party_size) FROM reservations
               WHERE res_date BETWEEN CURRENT_DATE AND CURRENT_DATE + %s
                 AND status IN ('requested', 'confirmed')
               GROUP BY res_date ORDER BY res_date""",
            (args.days,),
        ).fetchall()
    return {
        "days": args.days,
        "by_status": {s: n for s, n in by_status},
        "by_date": [{"date": str(d), "reservations": n, "guests": int(g)} for d, n, g in by_date],
    }


class RunSqlArgs(BaseModel):
    """고정 도구로 답할 수 없는 질문에 한해, 읽기 전용 SELECT 한 문장을 실행한다.

    테이블: customers(id,name,phone) · dining_tables(id,name,capacity,location)
    · reservations(id,customer_id,table_id,res_date,res_time,party_size,status,note,created_at,decided_at)
    """

    query: str = Field(min_length=1, description="실행할 SELECT 쿼리 한 문장 (세미콜론 없이)")


def run_sql(args: RunSqlArgs) -> dict:
    query = args.query.strip().rstrip(";").strip()
    if not query.lower().startswith("select"):
        return {"error": "SELECT로 시작하는 조회만 허용된다. 쓰기·DDL은 이 도구의 일이 아니다."}
    if ";" in query:
        return {"error": "한 문장만 허용된다."}
    if " limit " not in query.lower():
        query += " LIMIT 50"
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute("SET TRANSACTION READ ONLY")   # 마지막 방어선: pg가 쓰기를 거부
            cur = conn.execute(query)
            columns = [d.name for d in cur.description]
            rows = cur.fetchmany(50)
    except psycopg.Error as e:
        return {"error": f"쿼리 실패: {e}"}
    return {"query": query, "columns": columns,
            "rows": [[str(v) if v is not None else None for v in row] for row in rows]}


REGISTRY: dict[str, tuple[type[BaseModel], object]] = {
    "list_reservations": (ListReservationsArgs, list_reservations),
    "reservation_stats": (ReservationStatsArgs, reservation_stats),
    "run_sql": (RunSqlArgs, run_sql),
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


def run_admin_tool(name: str, raw_arguments: str) -> str:
    entry = REGISTRY.get(name)
    if entry is None:
        return json.dumps({"error": f"없는 도구: {name}"}, ensure_ascii=False)
    args_model, fn = entry
    try:
        args = args_model.model_validate(json.loads(raw_arguments or "{}"))
    except (ValidationError, json.JSONDecodeError) as e:
        return json.dumps({"error": f"인자 검증 실패: {e}"}, ensure_ascii=False)
    return json.dumps(fn(args), ensure_ascii=False, default=str)
