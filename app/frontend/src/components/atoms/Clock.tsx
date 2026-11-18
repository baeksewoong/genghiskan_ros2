import { useEffect, useState } from "react";

interface ClockProps {
  className?: string;
}

const TIME_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

const DATE_FORMATTER = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "long",
  day: "numeric",
  weekday: "short",
});

/** 1초마다 갱신되는 실시간 시계. 도메인 타입을 모르는 범용 UI라 atom에 둔다
 * (키오스크 헤더에서 매장 브랜딩과 함께 쓰인다). */
export function Clock({ className = "" }: ClockProps) {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className={`kiosk-clock${className ? ` ${className}` : ""}`}>
      <span className="kiosk-clock-time">{TIME_FORMATTER.format(now)}</span>
      <span className="kiosk-clock-date">{DATE_FORMATTER.format(now)}</span>
    </div>
  );
}
