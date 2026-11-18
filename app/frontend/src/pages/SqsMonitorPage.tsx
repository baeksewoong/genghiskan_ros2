import { useEffect, useState } from "react";
import { QueueStatusCard } from "../components/organisms/QueueStatusCard";
import { SqsLogPanel } from "../components/organisms/SqsLogPanel";
import { SqsMonitorTemplate } from "../components/templates/SqsMonitorTemplate";
import { summarize, useLiveState, type LogEntry } from "../hooks/useLiveState";
import { api } from "../lib/api";
import type { SqsStatus } from "../types";

const POLL_INTERVAL_MS = 3000;

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
    <SqsMonitorTemplate
      commandQueue={<QueueStatusCard title="robot-commands (발행)" status={status?.command_queue ?? null} />}
      eventQueue={<QueueStatusCard title="robot-events (수신)" status={status?.event_queue ?? null} />}
      statusError={statusError && <p className="sqs-status-error">큐 상태 조회 실패: {statusError}</p>}
      historyError={historyError && <p className="sqs-status-error">히스토리 조회 실패: {historyError}</p>}
      log={<SqsLogPanel log={combinedLog} />}
    />
  );
}
