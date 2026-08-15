"""booking-agent admin — 사장 운영 화면 (v1.0). 손님 화면과 완전히 다른 UI다.

비밀번호(.env의 ADMIN_PASSWORD) 하나로 들어오는 수업용 간이 인증.
[예약 관리] 탭은 승인/거절 워크플로(도메인 상태 머신)를, [운영 상담]
탭은 사장 어시스턴트(고정 도구 + 읽기 전용 SQL 도구)를 제공한다.
"""

import os
import uuid

import requests
import streamlit as st

APP_URL = os.environ.get("APP_URL", "http://localhost:8000")

st.set_page_config(page_title="소나무 — 사장", page_icon="🧑‍🍳", layout="wide")


def api(method: str, path: str, **kwargs):
    headers = {"x-admin-password": st.session_state.get("password", "")}
    r = requests.request(method, f"{APP_URL}{path}", headers=headers, timeout=120, **kwargs)
    r.raise_for_status()
    return r.json()


# ── 로그인: 비밀번호 하나 ────────────────────────────────────────────
if "password" not in st.session_state:
    st.title("🧑‍🍳 소나무 — 사장 화면")
    with st.form("login"):
        password = st.text_input("관리자 비밀번호", type="password")
        ok = st.form_submit_button("입장", use_container_width=True)
    if ok:
        st.session_state.password = password
        try:
            api("GET", "/admin/reservations")
        except requests.HTTPError:
            del st.session_state.password
            st.error("비밀번호가 틀렸습니다.")
            st.stop()
        st.rerun()
    st.stop()

st.title("🧑‍🍳 소나무 — 사장 화면")
manage, consult = st.tabs(["📋 예약 관리", "💬 운영 상담"])

STATUS_LABEL = {"requested": "🕐 승인 대기", "confirmed": "✅ 확정",
                "declined": "❌ 거절됨", "cancelled": "🚫 취소됨"}

# ── 예약 관리: 승인/거절은 도메인 상태 머신 — 그래프는 멈춰 있지 않다 ──
with manage:
    pick = st.selectbox("보기", ["승인 대기", "전체", "확정", "거절됨", "취소됨"])
    status_param = {"승인 대기": "requested", "확정": "confirmed",
                    "거절됨": "declined", "취소됨": "cancelled"}.get(pick)
    data = api("GET", "/admin/reservations",
               params={"status": status_param} if status_param else None)
    rows = data["reservations"]

    counts = api("GET", "/admin/reservations")["reservations"]
    left, mid, right = st.columns(3)
    left.metric("승인 대기", sum(1 for r in counts if r["status"] == "requested"))
    mid.metric("확정", sum(1 for r in counts if r["status"] == "confirmed"))
    right.metric("예정 예약 전체", len(counts))

    if not rows:
        st.caption("해당하는 예약이 없습니다.")
    for r in rows:
        with st.container(border=True):
            info, actions = st.columns([4, 1])
            info.markdown(
                f"**{r['res_date']} {r['res_time']}** · {r['table']} · {r['party_size']}명 — "
                f"{r['customer']} ({r['phone']})  \n"
                f"{STATUS_LABEL.get(r['status'], r['status'])}"
                + (f" · 요청: {r['note']}" if r["note"] else "")
            )
            if r["status"] == "requested":
                if actions.button("승인", key=f"ok-{r['reservation_id']}", use_container_width=True):
                    api("POST", "/admin/decide",
                        json={"reservation_id": r["reservation_id"], "approved": True})
                    st.rerun()
                if actions.button("거절", key=f"no-{r['reservation_id']}", use_container_width=True):
                    api("POST", "/admin/decide",
                        json={"reservation_id": r["reservation_id"], "approved": False})
                    st.rerun()

# ── 운영 상담: 사장 어시스턴트 (고정 도구 + 읽기 전용 SQL) ────────────
with consult:
    if "admin_thread" not in st.session_state:
        st.session_state.admin_thread = f"admin-{uuid.uuid4().hex[:8]}"
        st.session_state.admin_history = []
    st.caption(
        f"상담 thread: `{st.session_state.admin_thread}` — 목록·통계는 고정 도구로, "
        "그 밖의 집계는 어시스턴트가 SELECT를 직접 작성해(읽기 전용) 조회합니다."
    )
    for role, content in st.session_state.admin_history:
        with st.chat_message(role):
            st.markdown(content)
    if prompt := st.chat_input("예: 이번 주 예약 현황 알려줘 / 요일별 손님 수를 집계해줘"):
        st.session_state.admin_history.append(("user", prompt))
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("확인 중…"):
                resp = api("POST", "/admin/chat",
                           json={"thread_id": st.session_state.admin_thread, "message": prompt})
            st.markdown(resp["answer"])
        st.session_state.admin_history.append(("assistant", resp["answer"]))
