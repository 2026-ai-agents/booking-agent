-- 시드: 테이블 7개 + 손님 2명 + 기존 예약 3건
--
-- 날짜는 CURRENT_DATE 기준 상대값 — 언제 기동해도 "내일 저녁"이 이미
-- 일부 차 있는 상태로 시작해, 가용 조회가 재미있어진다.

INSERT INTO dining_tables (name, capacity, location) VALUES
    ('창가1', 2,  '창가'),
    ('창가2', 2,  '창가'),
    ('홀1',   4,  '홀'),
    ('홀2',   4,  '홀'),
    ('홀3',   6,  '홀'),
    ('룸1',   6,  '룸'),
    ('룸2',   10, '룸');

INSERT INTO customers (name, phone) VALUES
    ('김서연', '010-1111-2222'),
    ('박지훈', '010-3333-4444');

INSERT INTO reservations (customer_id, table_id, res_date, res_time, party_size, status, decided_at) VALUES
    (1, (SELECT id FROM dining_tables WHERE name = '홀1'),
     CURRENT_DATE + 1, '18:00', 4, 'confirmed', now()),
    (2, (SELECT id FROM dining_tables WHERE name = '룸1'),
     CURRENT_DATE + 1, '19:00', 6, 'confirmed', now()),
    (2, (SELECT id FROM dining_tables WHERE name = '창가1'),
     CURRENT_DATE + 2, '12:00', 2, 'requested', NULL);
