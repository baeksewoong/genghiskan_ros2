-- 업장을 새로 시작한다고 가정하고 DB를 초기 상태로 되돌린다.
-- 주문/유저/로봇작업/이벤트로그는 전부 비우고, 프린터 3대와 적재대 3층은 모두 EMPTY로.
--
-- 실행: docker compose exec -T mysql mysql -u root -proot printshop < scripts/reset_db.sql
-- (app/ 디렉터리에서 실행)

SET FOREIGN_KEY_CHECKS = 0;

-- orders를 참조하는 FK부터 끊는다.
UPDATE printers SET current_order_id = NULL;

TRUNCATE TABLE robot_tasks;
TRUNCATE TABLE orders;
TRUNCATE TABLE users;
TRUNCATE TABLE event_logs;

UPDATE printers SET status = 'EMPTY', current_order_id = NULL, timer_ends_at = NULL, updated_at = NOW();
UPDATE board_stock SET status = 'EMPTY', updated_at = NOW();

SET FOREIGN_KEY_CHECKS = 1;
