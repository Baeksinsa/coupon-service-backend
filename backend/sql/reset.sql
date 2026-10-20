-- 테스트 전 초기화 (PRD 7.2: 테스트마다 사전 초기화)
-- psql ... -v event_id=1 -v qty=100 -f reset.sql   (두 변수 모두 필수)

BEGIN;
DELETE FROM coupon_issues WHERE event_id = :event_id;
UPDATE events SET total_qty = :qty, remaining_qty = :qty WHERE id = :event_id;
COMMIT;

SELECT id, name, total_qty, remaining_qty FROM events WHERE id = :event_id;
SELECT COUNT(*) AS issued_count FROM coupon_issues WHERE event_id = :event_id;
