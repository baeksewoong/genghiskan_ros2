import { useState } from "react";
import { SHAPE_LABEL } from "../../constants";
import { parseServerTime } from "../../lib/time";
import type { Order } from "../../types";

interface PickupPanelProps {
  orders: Order[] | null;
  onPickUp: (orderId: number) => Promise<void>;
}

function formatCompletedAt(iso: string): string {
  return new Date(parseServerTime(iso)).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

/** 수령대(READY_FOR_PICKUP) 현황 표시 — 누가 어떤 작업을 찾아가야 하는지, 언제 작업이
 * 완료됐는지 보여준다. "수령하기"를 눌러야만 수령대에서 내려간다(자동 수령 없음). */
export function PickupPanel({ orders, onPickUp }: PickupPanelProps) {
  const [pickingUpId, setPickingUpId] = useState<number | null>(null);

  const handlePickUp = async (orderId: number) => {
    if (pickingUpId !== null) return;
    setPickingUpId(orderId);
    try {
      await onPickUp(orderId);
    } finally {
      setPickingUpId(null);
    }
  };

  return (
    <section className="panel pickup-panel">
      <h2>수령대 현황</h2>
      {!orders ? (
        <p>불러오는 중...</p>
      ) : orders.length === 0 ? (
        <p>수령 대기중인 주문이 없습니다.</p>
      ) : (
        <ul className="pickup-list">
          {orders.map((o) => (
            <li key={o.id}>
              <span className="pickup-info">
                <span className="pickup-customer-name">{o.customer_name ?? `주문 #${o.id}`}</span>
                <span className="pickup-shape">{SHAPE_LABEL[o.shape]}</span>
                {o.print_completed_at && (
                  <span className="pickup-completed-at">완료 {formatCompletedAt(o.print_completed_at)}</span>
                )}
              </span>
              <button onClick={() => handlePickUp(o.id)} disabled={pickingUpId === o.id}>
                {pickingUpId === o.id ? "수령 처리중..." : "수령하기"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
