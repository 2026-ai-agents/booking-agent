"""v0.1 사고 재현: 기억은 app 서버 프로세스의 메모리에 산다.

MemorySaver의 thread 저장소는 **서버 프로세스** 안에 있다. 그래서 이
데모는 그래프를 직접 부르지 않고 서버의 /chat API로 말을 건다 —
재시작으로 사라지는 것이 바로 그 프로세스이기 때문이다. (그래프를 직접
import하면 exec마다 새 프로세스라, 재시작과 무관하게 항상 백지가 된다)

    docker compose exec app python demos/amnesia.py          # 1부: 두 턴 대화
    docker compose exec app python demos/amnesia.py --probe  # 기억 확인 → 기억함
    docker compose restart app
    docker compose exec app python demos/amnesia.py --probe  # 재시작 후 → 백지

--probe가 재시작 전에는 기억하고 후에는 백지가 되는 것, 그 차이가 v0.1의
결핍 전부다. v0.2가 PostgreSQL checkpointer로 답한다.
"""

import sys

import httpx

APP = "http://localhost:8000"


def turn(message: str) -> None:
    r = httpx.post(
        f"{APP}/chat",
        json={
            "customer_id": 1,
            "customer_name": "김서연",
            "thread_id": "demo-amnesia",
            "message": message,
        },
        timeout=120,
    )
    r.raise_for_status()
    print(f"[손님] {message}")
    data = r.json()
    if data.get("interrupt"):      # v0.3부터 예약 요청은 확인 카드에서 멈춘다
        print(f"[확인 카드 대기] {data['interrupt']['requests']}\n")
    else:
        print(f"[상담사] {data['answer']}\n")


if "--probe" in sys.argv:
    print("=== 기억 확인: 같은 thread에 이어 묻는다 ===\n")
    turn("방금 제가 몇 명이라고 했죠?")
else:
    print("=== 1부: 서버의 /chat으로 두 턴 ===\n")
    turn("다음 주 금요일 저녁에 6명 모임이 있어요. 룸 자리 있을까요?")
    turn("19시가 좋겠어요.")
    print("이제 --probe로 기억을 확인하고, restart 후 --probe를 다시 해보세요.")
