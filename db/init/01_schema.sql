-- booking-agent 스키마: 한식당 '소나무'의 테이블 예약
--
-- 예약은 정시 슬롯 하나를 차지한다 (수업용 단순화 — 한 팀이 한 슬롯).
-- status가 예약의 생애를 나른다: requested(손님 신청) → confirmed(사장 승인)
--                              / declined(사장 거절) / cancelled(손님 취소)
-- LangGraph checkpointer 테이블(checkpoints 등)은 여기 없다 —
-- v0.2에서 PostgresSaver.setup()이 같은 db에 직접 만든다.

CREATE TABLE customers (
    id         serial PRIMARY KEY,
    name       text NOT NULL,
    phone      text NOT NULL UNIQUE,      -- 가벼운 로그인의 식별자
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE dining_tables (
    id       serial PRIMARY KEY,
    name     text NOT NULL UNIQUE,        -- 창가1, 홀2, 룸1 …
    capacity int  NOT NULL,
    location text NOT NULL                -- 창가 / 홀 / 룸
);

CREATE TABLE reservations (
    id          serial PRIMARY KEY,
    customer_id int  NOT NULL REFERENCES customers(id),
    table_id    int  NOT NULL REFERENCES dining_tables(id),
    res_date    date NOT NULL,
    res_time    time NOT NULL,            -- 영업 슬롯 정시 (11:00~20:00)
    party_size  int  NOT NULL CHECK (party_size BETWEEN 1 AND 12),
    status      text NOT NULL DEFAULT 'requested'
                CHECK (status IN ('requested', 'confirmed', 'declined', 'cancelled')),
    note        text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    decided_at  timestamptz               -- 사장이 승인/거절한 시각
);

CREATE INDEX idx_reservations_slot ON reservations (table_id, res_date, res_time);
