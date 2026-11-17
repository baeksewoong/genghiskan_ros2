import type { ReactNode } from "react";

interface SqsMonitorTemplateProps {
  commandQueue: ReactNode;
  eventQueue: ReactNode;
  statusError?: ReactNode;
  historyError?: ReactNode;
  log: ReactNode;
}

export function SqsMonitorTemplate({
  commandQueue,
  eventQueue,
  statusError,
  historyError,
  log,
}: SqsMonitorTemplateProps) {
  return (
    <div className="app">
      <header className="topbar">
        <h1>SQS 모니터링</h1>
      </header>

      <main className="layout">
        {commandQueue}
        {eventQueue}
      </main>

      {statusError}
      {historyError}

      {log}
    </div>
  );
}
