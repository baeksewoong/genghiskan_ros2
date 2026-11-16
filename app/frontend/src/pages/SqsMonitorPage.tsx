import { useEffect, useState } from "react";
import { Pill } from "../components/atoms/Pill";
import { useLiveState } from "../hooks/useLiveState";
import { api } from "../lib/api";
import type { SqsQueueStatus, SqsStatus } from "../types";

const POLL_INTERVAL_MS = 3000;

function QueueStatusCard({ title, status }: { title: string; status: SqsQueueStatus | null }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {!status ? (
        <p>불러오는 중...</p>
      ) : !status.configured ? (
        <Pill variant="bad">큐 미설정</Pill>
      ) : status.error ? (
        <Pill variant="bad">조회 실패: {status.error}</Pill>
      ) : (
        <div className="sqs-counts">
          <div>
            <span className="sqs-count-value">{status.visible}</span>
            <span className="sqs-count-label">대기중</span>
          </div>
          <div>
            <span className="sqs-count-value">{status.in_flight}</span>
            <span className="sqs-count-label">처리중(invisible)</span>
          </div>
          <div>
            <span className="sqs-count-value">{status.delayed}</span>
            <span className="sqs-count-label">지연</span>
          </div>
        </div>
      )}
    </section>
  );
}

export function SqsMonitorPage() {
  const { sqsLog } = useLiveState();
  const [status, setStatus] = useState<SqsStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const s = await api.getSqsStatus();
        if (!cancelled) {
          setStatus(s);
          setStatusError(null);
        }
      } catch (e) {
        if (!cancelled) setStatusError(String(e));
      }
    }

    poll();
    const timer = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <h1>SQS 모니터링</h1>
      </header>

      <main className="layout">
        <QueueStatusCard title="robot-commands (발행)" status={status?.command_queue ?? null} />
        <QueueStatusCard title="robot-events (수신)" status={status?.event_queue ?? null} />
      </main>

      {statusError && <p className="sqs-status-error">큐 상태 조회 실패: {statusError}</p>}

      <section className="panel sqs-log">
        <h2>메시지 로그 ({sqsLog.length})</h2>
        {sqsLog.length === 0 ? (
          <p>아직 수신/발행된 메시지가 없습니다.</p>
        ) : (
          <ul>
            {sqsLog.map((entry) => (
              <li key={entry.id}>
                <div>
                  <span className="log-ts">{entry.ts}</span>
                  {entry.summary}
                </div>
                <pre className="sqs-log-body">{JSON.stringify(entry.data, null, 2)}</pre>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
