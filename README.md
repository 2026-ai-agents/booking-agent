# booking-agent — 식당 예약 웹앱

AI Agent 실전 과정 Day 2 ②. 한식당 '소나무'의 예약을 대화로 잡는
에이전트입니다. **에이전트의 상태가 어디에 사는가**가 이 저장소의
주제입니다: 프로세스 메모리의 휘발(v0.1)에서 PostgreSQL 영속화(v0.2),
확정 전 사람 확인(v0.3), 관리자 입장과 time-travel(v1.0)까지.

- 강의 사이트: [2026-ai-agents.github.io/2026-ai-agents](https://2026-ai-agents.github.io/2026-ai-agents/)
- 컨테이너 4개: `app`(FastAPI + 그래프 2개) · `ui`(손님 화면) · `admin`(사장 화면) · `db`(PostgreSQL)

## 시작하기

```bash
git clone https://github.com/2026-ai-agents/booking-agent.git
cd booking-agent
cp .env.sample .env        # 키 채우기 (셋 중 하나면 됨)
docker compose up --build
```

- ui → http://localhost:8501 (손님 예약 화면 — 이름+전화로 로그인)
- admin → http://localhost:8502 (사장 화면 — `.env`의 ADMIN_PASSWORD로 로그인)
- app → http://localhost:8000/docs (API)
- 테스트: `docker compose exec app pytest` (LLM 키 불필요, db는 진짜)

## 릴리즈 사다리

세션 진행과 1:1로 대응합니다. `git checkout <태그>` 후 `docker compose up
--build` 하면 그 시점의 동작이 재현됩니다.

| 릴리즈 | 상태 |
| --- | --- |
| v0.1 | 손님 예약 대화 (MemorySaver) — 재시작하면 모든 대화가 백지 |
| v0.2 | PostgreSQL checkpointer — 재시작 생존, 상태는 SQL로 열어 읽는 행 |
| v0.3 | 확정 직전 interrupt — 쓰기 도구 앞에서 멈추고, 사람 결정으로 갈린다 |
| v1.0 | 사장 입장 완성(승인 워크플로·상담 에이전트·SQL 도구) + 손님 조회·취소 + time-travel |

## 저장소 구조

```plaintext
booking-agent/
├── docker-compose.yml      # app · ui · db
├── db/init/                # 스키마 + 시드 (테이블 7, 손님 2, 예약 3)
├── app/
│   ├── main.py             # FastAPI: 손님(/login /chat /confirm) + 사장(/admin/*)
│   ├── agent/config.py     # 모델 문자열이 사는 유일한 곳
│   ├── agent/graph.py      # ★ 교재의 중심 — 손님 예약 그래프 (confirm interrupt)
│   ├── agent/tools.py      # 가용 확인 · 신청 · 내 예약 · 취소 (신원은 주입)
│   ├── agent/admin_graph.py# 사장 어시스턴트 그래프 (조회 전용)
│   ├── agent/admin_tools.py# 고정 도구 2 + 읽기 전용 run_sql (세 겹 방어)
│   ├── demos/              # 시연 스크립트
│   └── tests/              # 유닛 테스트 (LLM은 각본 대역)
├── ui/app.py               # 손님 화면 (Streamlit, :8501)
└── admin/app.py            # 사장 화면 (Streamlit, :8502) — 완전히 다른 UI
```

## 시연 스크립트

```bash
docker compose exec app python demos/amnesia.py          # 1부: 두 턴 대화
docker compose exec app python demos/amnesia.py --probe  # 기억 확인 → 기억함
docker compose restart app
docker compose exec app python demos/amnesia.py --probe  # 재시작 후 → v0.1 백지 · v0.2 기억함
docker compose exec app python demos/dump_checkpoint.py  # v0.2: 저장된 상태를 SQL과 그래프로 열어 읽기
docker compose exec app python demos/approve_flow.py            # v0.3: interrupt → 승인 → 그제야 쓴다
docker compose exec app python demos/approve_flow.py --decline  # v0.3: interrupt → 보류 → 안 쓴다
docker compose exec app python demos/admin_sql.py               # v1.0: 사장 어시스턴트 + SQL 세 겹 방어
docker compose exec app python demos/time_travel.py             # v1.0: 과거 checkpoint에서 평행 재생
```

## 데이터의 수명

db 데이터(예약·대화 checkpoint)는 이름 있는 볼륨 `pgdata`에 삽니다.

| 명령 | 데이터 |
| --- | --- |
| `docker compose restart` | 유지 |
| `docker compose down` 후 `up` | **유지** (v1.2.0부터) |
| `docker compose down -v` | 초기화 — 시드부터 다시 시작 |

과거 태그(v0.1\~v1.1.0)의 compose에는 이 볼륨이 없어, 태그 체크아웃 후
기동하면 항상 깨끗한 시드로 시작합니다. 릴리즈 사다리 재현에는 그쪽이
의도된 동작입니다.

## 예약의 생애 (status)

```
requested (손님 신청) ──승인──> confirmed
                     └─거절──> declined        cancelled (손님 취소)
```

신청은 접수일 뿐이고, 사장 승인이 나야 확정입니다. 두 입장의 "승인"은
성격이 다릅니다: 손님의 확인 카드는 그래프의 interrupt(쓰기 직전 멈춤),
사장의 승인은 도메인 상태 머신(행이 바뀔 뿐, 그래프는 멈추지 않음)입니다.

## git 워크플로

git flow를 따릅니다: `develop`에서 `feature/*` 분기, 릴리즈는
`release/<태그>`를 거쳐 `main` 머지 + 태그. `main`은 항상 완성본입니다.
