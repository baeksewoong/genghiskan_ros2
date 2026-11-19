// 서버는 datetime.utcnow() 기반 naive UTC 시각을 타임존 표시 없이 보낸다
// (예: "2026-11-12T12:43:46.504899"). 표시가 없으면 new Date()가 이를
// 로컬 시간으로 오해해 UTC+N 지역에서는 N시간만큼 과거로 계산되므로, UTC로 간주해 파싱한다.
export function parseServerTime(iso: string): number {
  const hasTimezone = /Z$|[+-]\d{2}:?\d{2}$/.test(iso);
  return new Date(hasTimezone ? iso : `${iso}Z`).getTime();
}

// 작업 히스토리 페이지 전용: 서버 타임스탬프를 사람이 읽을 수 있는 로컬 날짜/시각
// 문자열로 바꾼다. null/undefined(아직 발생하지 않은 이벤트)는 "-"로 표시한다.
export function formatServerTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  return new Date(parseServerTime(iso)).toLocaleString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
