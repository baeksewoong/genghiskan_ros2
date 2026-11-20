import { useState } from "react";
import { SHAPE_LABEL } from "../../constants";
import { parseServerTime } from "../../lib/time";
import { Pill } from "../atoms/Pill";
import type { Order, ReceivePos, ReceivePosStatus } from "../../types";

const STATUS_LABEL: Record<ReceivePosStatus, string> = {
  EMPTY: "비어있음",
  RESERVED: "로봇 이동 중",
  OCCUPIED: "수령 대기",
};

// 수령대는 비어 있어야 다음 완성품을 받을 수 있으므로 EMPTY가 "ok"다 (적재대와 반대).
const STATUS_VARIANT: Record<ReceivePosStatus, "ok" | "bad" | "neutral"> = {
  EMPTY: "ok",
  RESERVED: "neutral",
  OCCUPIED: "bad",
};

interface ReceivePosPanelProps {
  positions: ReceivePos[] | null;
  /** 수령대에 올라간 주문 상세(손님 이름/모양/완료 시각) 조회용. */
  orders: Order[];
  onPickUp: (orderId: number) => Promise<void>;
}

function formatCompletedAt(iso: string): string {
  return new Date(parseServerTime(iso)).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

/** 수령대(1, 2번) 현황. 로봇은 비어있는 곳 중 번호가 작은 쪽(1번 우선)에 완성품을
 * 내려놓는다. 완성품이 놓인 칸(OCCUPIED)에서 "수령하기"를 누르면 그 칸이 비고, 수령대가
 * 가득 차서 대기 중이던 완성품이 있으면 서버가 자동으로 이어서 가져온다. */
export function ReceivePosPanel({ positions, orders, onPickUp }: ReceivePosPanelProps) {
  const [pickingUpId, setPickingUpId] = useState<number | null>(null);
  const orderById = new Map(orders.map((o) => [o.id, o]));
  const allFull = !!positions && positions.length > 0 && positions.every((p) => p.status !== "EMPTY");

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
    <section className="panel kiosk-card receive-pos-panel">
      <h2>
        <span className="kiosk-card-icon" aria-hidden="true">
          📬
        </span>
        수령대 현황
      </h2>
      {!positions ? (
        <p>불러오는 중...</p>
      ) : (
        <>
          <ul className="receive-pos-list">
            {[...positions]
              .sort((a, b) => a.pos_id - b.pos_id)
              .map((p) => {
                const order = p.current_order_id !== null ? orderById.get(p.current_order_id) : undefined;
                return (
                  <li key={p.pos_id}>
                    <div className="slot-row-top">
                      <span className="receive-pos-slot">{p.pos_id}번</span>
                      {p.status === "OCCUPIED" && p.current_order_id !== null ? (
                        <button
                          onClick={() => handlePickUp(p.current_order_id!)}
                          disabled={pickingUpId === p.current_order_id}
                        >
                          {pickingUpId === p.current_order_id ? "수령 처리중..." : "수령하기"}
                        </button>
                      ) : (
                        <Pill variant={STATUS_VARIANT[p.status]}>{STATUS_LABEL[p.status]}</Pill>
                      )}
                    </div>
                    {/* 주문이 없어도 칸을 항상 렌더링해, 칸마다 데이터 유무로 행 높이가
                     * 들쭉날쭉해지지 않게 한다 (높이는 .slot-row-sub의 min-height가 보장). */}
                    <div className="slot-row-sub">
                      {p.current_order_id !== null && (
                        <>
                          <span className="pickup-customer-name">
                            {order?.customer_name ?? `주문 #${p.current_order_id}`}
                          </span>
                          {order && <span className="pickup-shape">{SHAPE_LABEL[order.shape]}</span>}
                          {order?.print_completed_at && (
                            <span className="pickup-completed-at">
                              완료 {formatCompletedAt(order.print_completed_at)}
                            </span>
                          )}
                        </>
                      )}
                    </div>
                  </li>
                );
              })}
          </ul>
          {allFull && <p className="receive-pos-full">수령대가 가득 찼습니다. 수령하기를 하면 이어서 진행됩니다.</p>}
        </>
      )}
    </section>
  );
}
