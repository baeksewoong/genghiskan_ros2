import { Pill } from "../atoms/Pill";
import type { BoardStockSlot, BoardStockSlotStatus } from "../../types";

const STATUS_LABEL: Record<BoardStockSlotStatus, string> = {
  OCCUPIED: "적재됨",
  RESERVED: "피킹 대기",
  EMPTY: "비어있음",
};

const STATUS_VARIANT: Record<BoardStockSlotStatus, "ok" | "bad" | "neutral"> = {
  OCCUPIED: "ok",
  RESERVED: "neutral",
  EMPTY: "bad",
};

interface BoardStockPanelProps {
  slots: BoardStockSlot[] | null;
}

/** 적재대(물리적으로 3개 층) 현황 표시. 로봇은 맨 위(슬롯 번호가 가장 큰 OCCUPIED
 * 층)부터 집으므로, 큰 슬롯 번호를 위로 오게 정렬해 실제 적재대 모양과 맞춘다. */
export function BoardStockPanel({ slots }: BoardStockPanelProps) {
  return (
    <section className="panel kiosk-card board-stock-panel">
      <h2>
        <span className="kiosk-card-icon" aria-hidden="true">
          📦
        </span>
        적재대 현황{slots && ` (${slots.length})`}
      </h2>
      {!slots ? (
        <p>불러오는 중...</p>
      ) : (
        <ul className="board-stock-list">
          {[...slots]
            .sort((a, b) => b.slot - a.slot)
            .map((s) => (
              <li key={s.slot}>
                <span className="board-stock-slot">{s.slot}층</span>
                <Pill variant={STATUS_VARIANT[s.status]}>{STATUS_LABEL[s.status]}</Pill>
              </li>
            ))}
        </ul>
      )}
    </section>
  );
}
