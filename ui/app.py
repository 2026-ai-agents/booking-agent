"""booking-agent ui — 손님 예약 화면 (v0.3).

로그인(이름+전화, 인증이 아니라 식별)을 거치면 예약 상담 채팅이 열린다.
thread는 손님마다 하나(cust-<id>)라 다시 로그인해도 같은 대화가 이어지고,
기억은 pg에 살아 서버를 재시작해도 이어진다.

v0.3: 에이전트가 예약을 실행하기 직전 확인 카드가 뜬다. 서버 그래프가
interrupt로 멈춘 것이고, 버튼의 결정이 /confirm으로 되돌아가야 이어진다.
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
        st.session_state.pending = None
        st.rerun()
    st.stop()

customer = st.session_state.customer
st.session_state.setdefault("pending", None)


def take(resp: dict) -> None:
    """서버 응답을 두 갈래로 받는다: 답이거나, 확인 대기거나."""
    if resp.get("interrupt"):
        st.session_state.pending = resp["interrupt"]
    else:
        st.session_state.history.append(("assistant", resp["answer"]))
        st.session_state.pending = None


with st.sidebar:
    st.title("🍽️ 소나무 — 예약")
    st.caption("booking-agent v0.3 · LangGraph")
    st.write(f"**{customer['name']}** 님 · `{customer['thread_id']}`")
    if st.button("로그아웃", use_container_width=True):
        for key in ("customer", "history", "pending"):
            st.session_state.pop(key, None)
        st.rerun()
    st.divider()
    st.markdown("**내 예약**")
    STATUS_BADGE = {"requested": "🕐 승인 대기", "confirmed": "✅ 확정",
                    "declined": "❌ 거절됨", "cancelled": "🚫 취소됨"}
    try:
        mine = requests.get(f"{APP_URL}/reservations/{customer['customer_id']}", timeout=10).json()
        if not mine["reservations"]:
            st.caption("예정된 예약이 없습니다.")
        for r in mine["reservations"]:
            st.caption(
                f"{r['res_date']} {r['res_time']} · {r['table']} · {r['party_size']}명  \n"
                f"{STATUS_BADGE.get(r['status'], r['status'])}"
            )
    except requests.RequestException:
        st.caption("예약 목록을 불러오지 못했습니다.")
    st.divider()
    st.markdown(
        "대화로 예약을 잡습니다.\n\n"
        "- 날짜·시간·인원을 말하면 빈 테이블을 찾아 드립니다\n"
        "- 예약 실행·취소 전에 확인 카드가 뜹니다\n"
        "- 신청은 사장님 승인 후 확정됩니다"
    )

# ── 지난 대화 다시 그리기 ────────────────────────────────────────────
for role, content in st.session_state.history:
    with st.chat_message(role):
        st.markdown(content)

# ── 확인 카드: 그래프가 interrupt로 멈춰 있다 ─────────────────────────
if st.session_state.pending:
    req = st.session_state.pending["requests"][0]
    with st.chat_message("assistant"):
        if "reservation_id" in req:        # 취소 확인
            st.warning(f"**예약 #{req['reservation_id']}을(를) 정말 취소할까요?**")
        else:                              # 신청 확인
            st.info(
                f"**이대로 예약을 신청할까요?**\n\n"
                f"- 날짜: {req.get('res_date')}  \n"
                f"- 시간: {req.get('res_time')}  \n"
                f"- 테이블: {req.get('table_name')}  \n"
                f"- 인원: {req.get('party_size')}명"
                + (f"  \n- 요청: {req.get('note')}" if req.get("note") else "")
            )
        left, right = st.columns(2)
        if left.button("✅ 진행", use_container_width=True):
            with st.spinner("신청 중…"):
                r = requests.post(f"{APP_URL}/confirm",
                                  json={"thread_id": customer["thread_id"], "approved": True},
                                  timeout=120)
                r.raise_for_status()
                take(r.json())
            st.rerun()
        if right.button("↩️ 아니요, 다시 이야기할게요", use_container_width=True):
            with st.spinner("전달 중…"):
                r = requests.post(f"{APP_URL}/confirm",
                                  json={"thread_id": customer["thread_id"], "approved": False,
                                        "reason": "손님이 조건을 바꾸고 싶어 한다"},
                                  timeout=120)
                r.raise_for_status()
                take(r.json())
            st.rerun()

# ── 입력 → /chat 왕복 ────────────────────────────────────────────────
if prompt := st.chat_input("예: 내일 저녁 7시에 4명 자리 있나요?",
                           disabled=st.session_state.pending is not None):
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
            take(r.json())
    st.rerun()
