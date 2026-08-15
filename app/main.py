"""booking-agent app — v0.1: 로그인(가벼운 식별)과 예약 상담.

로그인은 인증이 아니라 식별이다: 이름+전화가 customers 행이 되고, 그
id가 그래프 상태에 실려 도구 실행의 신원이 된다. 대화 thread는 손님마다
하나(cust-<id>)가 기본 — 같은 손님이 다시 로그인하면 같은 대화가 이어진다.
v0.2부터 그 기억이 pg에 살아서, 재시작해도 이어진다.
"""

import psycopg
from fastapi import FastAPI
from pydantic import BaseModel, Field

from agent.graph import graph
from agent.tools import DATABASE_URL

app = FastAPI(title="booking-agent", version="0.2")


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


class ChatBody(BaseModel):
    customer_id: int
    customer_name: str = "손님"
    thread_id: str
    message: str


@app.post("/chat")
def chat(body: ChatBody):
    config = {"configurable": {"thread_id": body.thread_id}}
    result = graph.invoke(
        {
            "messages": [{"role": "user", "content": body.message}],
            "customer_id": body.customer_id,
            "customer_name": body.customer_name,
        },
        config,
    )
    return {"answer": result["messages"][-1]["content"]}
