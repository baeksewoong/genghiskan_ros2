import type { ReactNode } from "react";

interface WorkHistoryTemplateProps {
  error?: ReactNode;
  history: ReactNode;
}

export function WorkHistoryTemplate({ error, history }: WorkHistoryTemplateProps) {
  return (
    <div className="app">
      <header className="topbar">
        <h1>작업 히스토리</h1>
      </header>

      {error}

      {history}
    </div>
  );
}
