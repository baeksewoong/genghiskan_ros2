import { SqsLogEntryItem } from "../molecules/SqsLogEntryItem";
import type { LogEntry } from "../../hooks/useLiveState";

interface SqsLogPanelProps {
  log: LogEntry[];
}

/** SQS로 발행/수신된 메시지 로그 패널 — 실시간 수신분(useLiveState)과 서버 히스토리를
 * 합친 목록을 그대로 받아 보여준다. */
export function SqsLogPanel({ log }: SqsLogPanelProps) {
  return (
    <section className="panel sqs-log">
      <h2>메시지 로그 ({log.length})</h2>
      {log.length === 0 ? (
        <p>아직 수신/발행된 메시지가 없습니다.</p>
      ) : (
        <ul>
          {log.map((entry) => (
            <SqsLogEntryItem key={entry.id} entry={entry} />
          ))}
        </ul>
      )}
    </section>
  );
}
