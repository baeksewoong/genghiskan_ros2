import type { ReactNode } from "react";

interface TeachingPendantTemplateProps {
  // "리모컨" 패널(RemoteControlPanel organism) — 활성화/상태/조그/그리퍼/정지가 전부
  // 탭으로 들어가 있다. 3D 뷰어는 홈 대시보드(DashboardTemplate)로 옮겨갔으므로 이
  // 템플릿은 더 이상 갖지 않는다.
  remoteControl: ReactNode;
}

/** 순수 레이아웃 — 모든 콘텐츠를 ReactNode로 받아 배치만 한다. */
export function TeachingPendantTemplate({ remoteControl }: TeachingPendantTemplateProps) {
  return (
    <div className="app">
      <header className="topbar">
        <h1>티칭 팬던트 (실물 로봇 조그 제어)</h1>
      </header>

      <div className="arm-dashboard-row">{remoteControl}</div>
    </div>
  );
}
