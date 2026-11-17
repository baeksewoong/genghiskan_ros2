import type { LogEntry } from "../../hooks/useLiveState";

interface SqsLogEntryItemProps {
  entry: LogEntry;
}

/** SQS 메시지 로그 한 줄 — 타임스탬프/요약과, 펼쳐진 원본 payload(JSON)를 보여준다.
 * 일반 이벤트 로그(`LogEntryItem`)와 달리 ts를 자르지 않고 그대로 보여주고 본문도
 * 함께 노출한다. */
export function SqsLogEntryItem({ entry }: SqsLogEntryItemProps) {
  return (
    <li>
      <div>
        <span className="log-ts">{entry.ts}</span>
        {entry.summary}
      </div>
      <pre className="sqs-log-body">{JSON.stringify(entry.data, null, 2)}</pre>
    </li>
  );
}
