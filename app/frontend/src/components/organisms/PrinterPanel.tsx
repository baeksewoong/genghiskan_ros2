import { useEffect, useState } from "react";
import { Pill } from "../atoms/Pill";
import { parseServerTime } from "../../lib/time";
import type { Printer, PrinterStatus } from "../../types";

const STATUS_LABEL: Record<PrinterStatus, string> = {
  EMPTY: "비어있음",
  RESERVED: "배치 대기",
  PRINTING: "출력중",
  DONE: "출력 완료",
};

const STATUS_VARIANT: Record<PrinterStatus, "ok" | "bad" | "neutral"> = {
  EMPTY: "ok",
  RESERVED: "neutral",
  PRINTING: "neutral",
  DONE: "ok",
};

interface PrinterPanelProps {
  printers: Printer[] | null;
}

function formatRemaining(ms: number): string {
  const totalSec = Math.max(0, Math.round(ms / 1000));
  const mm = Math.floor(totalSec / 60);
  const ss = totalSec % 60;
  return `${mm}:${String(ss).padStart(2, "0")}`;
}

/** printer.timer_ends_at까지 남은 시간을 1초마다 다시 계산해 보여준다. */
function PrinterTimer({ endsAt }: { endsAt: string }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const remainingMs = parseServerTime(endsAt) - now;
  return <span className="printer-timer">{formatRemaining(remainingMs)}</span>;
}

/** 3D 프린터 작업대(3대) 현황 표시. 실제 배치처럼 1층이 맨 아래에 오도록 슬롯
 * 번호 내림차순으로 보여준다 (빈 프린터를 고를 땐 반대로 가장 작은 번호부터
 * 쓴다 — PrinterRepository.first_empty_locked). */
export function PrinterPanel({ printers }: PrinterPanelProps) {
  return (
    <section className="panel kiosk-card printer-panel">
      <h2>
        <span className="kiosk-card-icon" aria-hidden="true">
          🖨️
        </span>
        작업대 현황
      </h2>
      {!printers ? (
        <p>불러오는 중...</p>
      ) : (
        <ul className="printer-list">
          {[...printers]
            .sort((a, b) => b.slot - a.slot)
            .map((p) => (
              <li key={p.slot}>
                <span className="printer-slot">
                  {p.slot}층
                  {p.customer_name && <span className="printer-customer-name">{p.customer_name}</span>}
                  {p.status === "PRINTING" && p.timer_ends_at && <PrinterTimer endsAt={p.timer_ends_at} />}
                </span>
                <Pill variant={STATUS_VARIANT[p.status]}>{STATUS_LABEL[p.status]}</Pill>
              </li>
            ))}
        </ul>
      )}
    </section>
  );
}
