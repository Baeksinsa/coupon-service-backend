-- 기본 이벤트 1건 (재고 100)
INSERT INTO events (id, name, total_qty, remaining_qty)
VALUES (1, '선착순 쿠폰 이벤트', 100, 100)
ON CONFLICT (id) DO UPDATE
    SET total_qty = EXCLUDED.total_qty,
        remaining_qty = EXCLUDED.remaining_qty;
