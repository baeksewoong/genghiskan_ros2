-- 업장을 새로 시작한다고 가정하고 DB를 초기 상태로 되돌린다.
-- 주문/유저/로봇작업/이벤트로그는 전부 비우고, 프린터 3대·적재대 3층·수령대 2곳은 모두 EMPTY로.
--
-- 실행: docker compose exec -T mysql mysql -u root -proot printshop < scripts/reset_db.sql
-- (app/ 디렉터리에서 실행)

SET FOREIGN_KEY_CHECKS = 0;

-- orders를 참조하는 FK부터 끊는다.
UPDATE printers SET current_order_id = NULL;
UPDATE receive_pos SET current_order_id = NULL;

TRUNCATE TABLE robot_tasks;
TRUNCATE TABLE orders;
TRUNCATE TABLE users;
TRUNCATE TABLE event_logs;

-- TRUNCATE는 AUTO_INCREMENT를 1로 되돌린다. work_id(=order id)가 재사용되면
-- SQS FIFO 큐의 MessageDeduplicationId("load-{work_id}" 등)가 직전 리셋 때
-- 보낸 메시지와 같아져서, 5분 중복 제거 윈도우 안에 재테스트하면 두 번째
-- LOAD 명령이 조용히 버려진다. 매번 다른 값으로 올려서 재사용을 막는다.
-- (ALTER TABLE ... AUTO_INCREMENT = <값>은 상수 리터럴만 허용해서 함수 호출을
-- 바로 못 쓴다 — PREPARE/EXECUTE로 문자열을 만들어 동적 실행한다.)
SET @reset_auto_increment = CONCAT('ALTER TABLE orders AUTO_INCREMENT = ', UNIX_TIMESTAMP());
PREPARE stmt FROM @reset_auto_increment;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE printers SET status = 'EMPTY', current_order_id = NULL, timer_ends_at = NULL, updated_at = NOW();
UPDATE board_stock SET status = 'EMPTY', updated_at = NOW();
UPDATE receive_pos SET status = 'EMPTY', current_order_id = NULL, updated_at = NOW();

SET FOREIGN_KEY_CHECKS = 1;
