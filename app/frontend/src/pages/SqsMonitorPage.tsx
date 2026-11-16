import { useEffect, useState } from "react";
import { Pill } from "../components/atoms/Pill";
import { summarize, useLiveState, type LogEntry } from "../hooks/useLiveState";
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
  const [history, setHistory] = useState<LogEntry[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);

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

  useEffect(() => {
    // 이 페이지를 열기 전에 오간 메시지도 보이도록, 서버에 저장된 히스토리를 한 번
    // 불러온다. 그 이후부터는 useLiveState의 실시간 sqsLog가 이어서 쌓인다.
    api
      .getSqsHistory()
      .then((envelopes) => {
        setHistory(
          envelopes.map((e) => ({
            id: e.event_id,
            ts: e.ts,
            type: e.type,
            summary: summarize(e.type, e.data),
            data: e.data,
          }))
        );
      })
      .catch((e) => setHistoryError(String(e)));
  }, []);

  const liveIds = new Set(sqsLog.map((entry) => entry.id));
  const combinedLog = [...sqsLog, ...history.filter((entry) => !liveIds.has(entry.id))];

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
      {historyError && <p className="sqs-status-error">히스토리 조회 실패: {historyError}</p>}

      <section className="panel sqs-log">
        <h2>메시지 로그 ({combinedLog.length})</h2>
        {combinedLog.length === 0 ? (
          <p>아직 수신/발행된 메시지가 없습니다.</p>
        ) : (
          <ul>
            {combinedLog.map((entry) => (
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
