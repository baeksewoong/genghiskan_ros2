import { SHAPE_LABEL } from "../../constants";
import type { Order } from "../../types";

interface OrderListItemProps {
  order: Order;
}

export function OrderListItem({ order }: OrderListItemProps) {
  return (
    <li>
      <span className="receive-pos-info">
        <span className="pickup-customer-name">{order.customer_name ?? `주문 #${order.id}`}</span>
        <span className="pickup-shape">{SHAPE_LABEL[order.shape]}</span>
      </span>
    </li>
  );
}
