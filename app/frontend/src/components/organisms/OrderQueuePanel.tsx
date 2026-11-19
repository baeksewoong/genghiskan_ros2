import { OrderListItem } from "../molecules/OrderListItem";
import type { Order } from "../../types";

interface OrderQueuePanelProps {
  icon: string;
  title: string;
  orders: Order[];
  emptyLabel: string;
}

export function OrderQueuePanel({ icon, title, orders, emptyLabel }: OrderQueuePanelProps) {
  return (
    <section className="panel kiosk-card queue order-queue-panel">
      <h2>
        <span className="kiosk-card-icon" aria-hidden="true">
          {icon}
        </span>
        {title} ({orders.length})
      </h2>
      {orders.length === 0 ? (
        <p className="order-queue-empty">{emptyLabel}</p>
      ) : (
        <ul className="order-queue-list">
          {orders.map((order) => (
            <OrderListItem key={order.id} order={order} />
          ))}
        </ul>
      )}
    </section>
  );
}
