# CLAUDE.md

AI Agent 실전 Day 2 ②: 상태의 거처를 배우는 식당 예약 웹 제품. 릴리즈
사다리 v0.1(메모리 대화) → v0.2(pg 영속화) → v0.3(interrupt 확인) →
v1.0(관리자 입장 + time-travel)으로 자란다. 이 문서는 이 저장소에서
작업하는 AI 도구를 위한 가이드다.

## 실행·검증 (전부 컨테이너에서)

```sh
docker compose up --build          # app(8000) · ui(8501) · admin(8502) · db 기동
docker compose exec app pytest     # 유닛 테스트 — LLM은 각본 대역, db는 진짜
docker compose exec app python demos/amnesia.py   # 시연은 app/demos/
```

로컬 파이썬으로 돌리지 않는다. 테스트는 키 없이 통과해야 정상이다.

## Git 워크플로: git flow

- `develop`에서 `feature/*` 분기 → `develop` 머지. `main` 직접 커밋 금지
- 릴리즈 사다리: `release/<태그>` → `main` 머지 + annotated 태그 + GitHub
  Release + `develop` 역머지. **태그를 옮기거나 지우지 않는다** — 태그가
  곧 교재다
- 수정이 이전 태그의 동작을 바꾸면 안 된다. 각 태그는 그 시점의 요구를
  따른다

## 코드 규칙

- 모델 문자열은 `app/agent/config.py`에만 (day-01·diet-agent와 같은 규약)
- `app/agent/graph.py`가 교재의 중심 — 수정 시 강의 사이트의
  day-02-session-03 문서와 동기화한다
- 도구는 pydantic 모델 + `run_tool` 관문 하나. 에러도 결과로 돌려준다.
  **신원(customer_id)은 LLM 인자가 아니라 상태에서 주입한다**
- 예약 status는 requested/confirmed/declined/cancelled 네 값뿐
- 두 "승인"을 섞지 않는다: 손님 확인은 interrupt, 사장 승인은 상태 머신
- run_sql의 세 겹 방어(SELECT 한 문장·자동 LIMIT·READ ONLY)를 깎지 않는다
- 데모 스크립트는 결정적이거나 사고 재현이 목적임을 docstring에 밝힌다
- 새 기능에는 테스트를 함께. `tests/conftest.py`의 각본 대역을 쓰고,
  쓰기 테스트는 2099년 날짜를 쓰며 정리(fixture)까지 책임진다
- `.env`는 절대 커밋하지 않는다

## 강의 사이트와의 동기화

이 저장소의 내용이 바뀌면 강의 사이트(`2026-ai-agents`)의
day-02-session-03 문서도 함께 고친다. 코드 발췌·시연 출력·스크린샷이
문서에 그대로 실린다.
