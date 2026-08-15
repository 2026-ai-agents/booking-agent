"""booking-agent app — v1.0: 손님 입장과 사장 입장이 한 앱에 산다.

손님 쪽(/login /chat /confirm /reservations)은 이름+전화 식별과 확인
카드를 거치는 예약 대화. 사장 쪽(/admin/*)은 비밀번호 헤더 뒤에서
승인/거절 워크플로와 운영 어시스턴트 대화를 제공한다.

두 입장의 "승인"은 성격이 다르다. 손님의 확인은 그래프의 interrupt
(쓰기 직전 멈춤)이고, 사장의 승인은 도메인 상태 머신(requested →
confirmed/declined)이다. 그래프는 멈추지 않는다 — 행이 바뀔 뿐이다.
"""

import os

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException
from langgraph.types import Command
from pydantic import BaseModel, Field

from agent.admin_graph import admin_graph
from agent.graph import graph
from agent.tools import DATABASE_URL

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

app = FastAPI(title="booking-agent", version="1.0")


@app.get("/health")
def health():
    return {"ok": True, "version": app.version}


class LoginBody(BaseModel):
    name: str = Field(min_length=1)
    phone: str = Field(min_length=4)


@app.post("/login")
def login(body: LoginBody):
    """이름+전화로 손님을 찾거나 만든다. 같은 전화는 언제나 같은 손님이다."""
    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute(
            """INSERT INTO customers (name, phone) VALUES (%s, %s)
               ON CONFLICT (phone) DO UPDATE SET name = EXCLUDED.name
               RETURNING id, name""",
            (body.name, body.phone),
        ).fetchone()
        conn.commit()
    customer_id, name = row
    return {"customer_id": customer_id, "name": name, "thread_id": f"cust-{customer_id}"}


@app.get("/reservations/{customer_id}")
def reservations(customer_id: int):
    """손님 화면 사이드바용 — 오늘 이후 예약과 상태."""
    with psycopg.connect(DATABASE_URL) as conn:
        rows = conn.execute(
            """SELECT r.id, r.res_date, r.res_time, t.name, r.party_size, r.status
               FROM reservations r JOIN dining_tables t ON t.id = r.table_id
               WHERE r.customer_id = %s AND r.res_date >= CURRENT_DATE
               ORDER BY r.res_date, r.res_time""",
            (customer_id,),
        ).fetchall()
    return {"reservations": [
        {"reservation_id": r[0], "res_date": str(r[1]), "res_time": str(r[2])[:5],
         "table": r[3], "party_size": r[4], "status": r[5]}
        for r in rows
    ]}


class ChatBody(BaseModel):
    customer_id: int
    customer_name: str = "손님"
    thread_id: str
    message: str


def run_graph(graph_input, thread_id: str) -> dict:
    """invoke 결과를 두 갈래로 갈라 준다: 답이 나왔거나, 확인을 기다리거나."""
    result = graph.invoke(graph_input, {"configurable": {"thread_id": thread_id}})
    if "__interrupt__" in result:
        return {"answer": None, "interrupt": result["__interrupt__"][0].value}
    return {"answer": result["messages"][-1]["content"], "interrupt": None}


@app.post("/chat")
def chat(body: ChatBody):
    return run_graph(
        {
            "messages": [{"role": "user", "content": body.message}],
            "customer_id": body.customer_id,
            "customer_name": body.customer_name,
        },
        body.thread_id,
    )


class ConfirmBody(BaseModel):
    thread_id: str
    approved: bool
    reason: str | None = None


@app.post("/confirm")
def confirm(body: ConfirmBody):
    """멈춘 그래프에 손님의 결정을 되돌려준다. 어디서 얼마나 늦게 와도 된다."""
    return run_graph(
        Command(resume={"approved": body.approved, "reason": body.reason}),
        body.thread_id,
    )


# ── 사장 입장 (/admin/*) — 수업용 간이 인증: 비밀번호 헤더 하나 ────────

def require_admin(x_admin_password: str = Header()):
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="관리자 비밀번호가 틀렸다")


@app.get("/admin/reservations", dependencies=[Depends(require_admin)])
def admin_reservations(status: str | None = None):
    clauses, params = ["r.res_date >= CURRENT_DATE"], []
    if status:
        clauses.append("r.status = %s")
        params.append(status)
    with psycopg.connect(DATABASE_URL) as conn:
        rows = conn.execute(
            f"""SELECT r.id, r.res_date, r.res_time, t.name, c.name, c.phone,
                       r.party_size, r.status, r.note
                FROM reservations r
                JOIN dining_tables t ON t.id = r.table_id
                JOIN customers c ON c.id = r.customer_id
                WHERE {' AND '.join(clauses)}
                ORDER BY r.res_date, r.res_time""",
            params,
        ).fetchall()
    return {"reservations": [
        {"reservation_id": r[0], "res_date": str(r[1]), "res_time": str(r[2])[:5],
         "table": r[3], "customer": r[4], "phone": r[5],
         "party_size": r[6], "status": r[7], "note": r[8]}
        for r in rows
    ]}


class DecideBody(BaseModel):
    reservation_id: int
    approved: bool


@app.post("/admin/decide", dependencies=[Depends(require_admin)])
def admin_decide(body: DecideBody):
    """사장의 승인/거절 — 도메인 상태 머신이다. 그래프는 멈춰 있지 않다."""
    new_status = "confirmed" if body.approved else "declined"
    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute(
            """UPDATE reservations SET status = %s, decided_at = now()
               WHERE id = %s AND status = 'requested'
               RETURNING id, status""",
            (new_status, body.reservation_id),
        ).fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=409, detail="승인 대기(requested) 상태가 아니다")
    return {"reservation_id": row[0], "status": row[1]}


class AdminChatBody(BaseModel):
    thread_id: str
    message: str


@app.post("/admin/chat", dependencies=[Depends(require_admin)])
def admin_chat(body: AdminChatBody):
    result = admin_graph.invoke(
        {"messages": [{"role": "user", "content": body.message}]},
        {"configurable": {"thread_id": body.thread_id}},
    )
    return {"answer": result["messages"][-1]["content"]}
