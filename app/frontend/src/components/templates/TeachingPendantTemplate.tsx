import type { ReactNode } from "react";

interface TeachingPendantTemplateProps {
  activation: ReactNode;
  status: ReactNode;
  modeControls: ReactNode;
  gripper: ReactNode;
  stop: ReactNode;
  jogPad: ReactNode;
}

/** 순수 레이아웃 — 모든 콘텐츠를 ReactNode로 받아 배치만 한다. 조그 패드는 12개
 * 방향키 버튼이 들어가므로 그리드 아래 전체 폭으로 따로 둔다. */
export function TeachingPendantTemplate({
  activation,
  status,
  modeControls,
  gripper,
  stop,
  jogPad,
}: TeachingPendantTemplateProps) {
  return (
    <div className="app">
      <header className="topbar">
        <h1>티칭 팬던트 (실물 로봇 조그 제어)</h1>
      </header>

      <main className="layout">
        {activation}
        {status}
        {modeControls}
        {gripper}
        {stop}
      </main>

      {jogPad}
    </div>
  );
}
