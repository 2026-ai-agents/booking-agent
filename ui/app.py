"""booking-agent ui — 손님 예약 화면 (v0.1).

로그인(이름+전화, 인증이 아니라 식별)을 거치면 예약 상담 채팅이 열린다.
thread는 손님마다 하나(cust-<id>)라 다시 로그인해도 같은 대화가 이어진다
— 단 v0.1의 기억은 app 프로세스 메모리다. 재시작하면 전부 사라진다.
"""

import os

import requests
import streamlit as st

APP_URL = os.environ.get("APP_URL", "http://localhost:8000")

st.set_page_config(page_title="소나무 — 예약", page_icon="🍽️")

# ── 로그인: 이름+전화가 손님 식별자다 ─────────────────────────────────
if "customer" not in st.session_state:
    st.title("🍽️ 한식당 소나무")
    st.caption("예약 상담을 시작하려면 이름과 전화번호를 알려 주세요.")
    with st.form("login"):
        name = st.text_input("이름", placeholder="김서연")
        phone = st.text_input("전화번호", placeholder="010-1234-5678")
        ok = st.form_submit_button("예약 상담 시작", use_container_width=True)
    if ok and name.strip() and phone.strip():
        r = requests.post(f"{APP_URL}/login", json={"name": name.strip(), "phone": phone.strip()}, timeout=10)
        r.raise_for_status()
        st.session_state.customer = r.json()
        st.session_state.history = []
        st.rerun()
    st.stop()

customer = st.session_state.customer

with st.sidebar:
    st.title("🍽️ 소나무 — 예약")
    st.caption("booking-agent v0.1 · LangGraph")
    st.write(f"**{customer['name']}** 님 · `{customer['thread_id']}`")
    if st.button("로그아웃", use_container_width=True):
        del st.session_state.customer
        st.session_state.history = []
        st.rerun()
    st.divider()
    st.markdown(
        "대화로 예약을 잡습니다.\n\n"
        "- 날짜·시간·인원을 말하면 빈 테이블을 찾아 드립니다\n"
        "- 신청은 사장님 승인 후 확정됩니다"
    )

# ── 지난 대화 다시 그리기 ────────────────────────────────────────────
for role, content in st.session_state.history:
    with st.chat_message(role):
        st.markdown(content)

# ── 입력 → /chat 왕복 ────────────────────────────────────────────────
if prompt := st.chat_input("예: 내일 저녁 7시에 4명 자리 있나요?"):
    st.session_state.history.append(("user", prompt))
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("확인 중…"):
            r = requests.post(
                f"{APP_URL}/chat",
                json={
                    "customer_id": customer["customer_id"],
                    "customer_name": customer["name"],
                    "thread_id": customer["thread_id"],
                    "message": prompt,
                },
                timeout=120,
            )
            r.raise_for_status()
            answer = r.json()["answer"]
        st.markdown(answer)
    st.session_state.history.append(("assistant", answer))
