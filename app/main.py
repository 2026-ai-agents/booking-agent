"""booking-agent app — v0.3: 확정 직전, 손님의 확인을 받는다.

로그인은 인증이 아니라 식별이다: 이름+전화가 customers 행이 되고, 그
id가 그래프 상태에 실려 도구 실행의 신원이 된다. 대화 thread는 손님마다
하나(cust-<id>)가 기본이고, 기억은 pg에 살아 재시작해도 이어진다.

v0.3에서 /chat의 응답이 두 갈래가 된다: 보통은 answer, 그래프가 확인을
위해 멈추면 interrupt 페이로드. 손님의 결정은 /confirm이 Command(resume)
로 그래프에 되돌려준다 — 멈춘 상태가 pg에 있으므로, 결정이 언제 오든
그 자리에서 이어진다.
"""

import psycopg
from fastapi import FastAPI
from langgraph.types import Command
from pydantic import BaseModel, Field

from agent.graph import graph
from agent.tools import DATABASE_URL

app = FastAPI(title="booking-agent", version="0.3")


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
