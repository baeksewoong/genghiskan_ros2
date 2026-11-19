import { Pill } from "../atoms/Pill";
import { SHAPE_LABEL } from "../../constants";
import { formatServerTime } from "../../lib/time";
import type { Order, OrderStatus } from "../../types";

const STATUS_LABEL: Record<OrderStatus, string> = {
  WAITING: "대기중",
  DISPATCHING: "투입 발행중",
  LOADING: "적재중",
  PRINTING: "출력중",
  PRINT_DONE: "출력 완료",
  UNLOADING: "수거중",
  READY_FOR_PICKUP: "수령 대기",
  PICKED_UP: "수령 완료",
};

const STATUS_VARIANT: Record<OrderStatus, "ok" | "bad" | "neutral"> = {
  WAITING: "neutral",
  DISPATCHING: "neutral",
  LOADING: "neutral",
  PRINTING: "neutral",
  PRINT_DONE: "ok",
  UNLOADING: "neutral",
  READY_FOR_PICKUP: "ok",
  PICKED_UP: "ok",
};

interface WorkHistoryPanelProps {
  orders: Order[] | null;
}

/** 작업 히스토리 페이지 전용 — 전체 주문을 최신순(생성 시각 내림차순)으로 보여준다.
 * 큐 표시용 OrderListItem/OrderQueuePanel은 필드가 다르고(대기열 중심) 상태뱃지/
 * 타임스탬프가 없어 그대로 재사용하지 않고 별도 표현으로 만들었다. */
export function WorkHistoryPanel({ orders }: WorkHistoryPanelProps) {
  return (
    <section className="panel work-history-panel">
      <h2>전체 주문 ({orders?.length ?? 0})</h2>
      {!orders ? (
        <p>불러오는 중...</p>
      ) : orders.length === 0 ? (
        <p className="order-queue-empty">아직 생성된 주문이 없습니다.</p>
      ) : (
        <ul className="work-history-list">
          {orders.map((order) => (
            <li key={order.id}>
              <div className="work-history-main">
                <span className="work-history-id">#{order.id}</span>
                <span className="pickup-customer-name">{order.customer_name ?? "익명"}</span>
                <span className="pickup-shape">{SHAPE_LABEL[order.shape]}</span>
                <Pill variant={STATUS_VARIANT[order.status]}>{STATUS_LABEL[order.status]}</Pill>
              </div>
              <div className="work-history-times">
                <span>생성 {formatServerTime(order.created_at)}</span>
                {order.picked_up_at && <span>수령 {formatServerTime(order.picked_up_at)}</span>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
