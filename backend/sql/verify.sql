-- 테스트 후 증거 수집 (T2/T3 판정)
-- psql ... -v event_id=1 -f verify.sql

SELECT id, name, total_qty, remaining_qty,
       total_qty - remaining_qty AS consumed
FROM events WHERE id = :event_id;

SELECT COUNT(*) AS issued_rows FROM coupon_issues WHERE event_id = :event_id;

-- 중복 발급이 단 1건도 없어야 한다 (0 rows 기대)
SELECT user_id, COUNT(*) AS dup
FROM coupon_issues WHERE event_id = :event_id
GROUP BY user_id HAVING COUNT(*) > 1;

-- 재고 차감과 발급 행 수가 일치해야 한다 (match 기대)
SELECT CASE
         WHEN (SELECT total_qty - remaining_qty FROM events WHERE id = :event_id)
            = (SELECT COUNT(*) FROM coupon_issues WHERE event_id = :event_id)
         THEN 'match' ELSE 'MISMATCH' END AS ledger_check;
