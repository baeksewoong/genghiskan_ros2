import { useEffect, useState } from "react";
import { NavSidebar } from "./components/organisms/NavSidebar";
import { DashboardPage } from "./pages/DashboardPage";
import { SqsMonitorPage } from "./pages/SqsMonitorPage";
import { TeachingPendantPage } from "./pages/TeachingPendantPage";
import { WorkHistoryPage } from "./pages/WorkHistoryPage";

const ROUTES = [
  { path: "#/", label: "home" },
  { path: "#/sqs-monitor", label: "SQS 모니터링" },
  { path: "#/teaching-pendant", label: "티칭 팬던트" },
  { path: "#/work-history", label: "작업 히스토리" },
];

function normalizeHash(hash: string): string {
  return hash === "" ? "#/" : hash;
}

export default function App() {
  const [hash, setHash] = useState(normalizeHash(location.hash));

  useEffect(() => {
    const onHashChange = () => setHash(normalizeHash(location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const isHome = hash === "#/";
  const otherPage =
    hash === "#/sqs-monitor" ? (
      <SqsMonitorPage />
    ) : hash === "#/teaching-pendant" ? (
      <TeachingPendantPage />
    ) : hash === "#/work-history" ? (
      <WorkHistoryPage />
    ) : null;

  return (
    <div className="app-shell">
      <NavSidebar routes={ROUTES} currentPath={hash} />
      <div className="app-shell-content">
        {/* 홈(DashboardPage)은 다른 라우트로 이동해도 언마운트하지 않고 CSS로만 숨긴다.
            홈에 있는 3D 로봇 뷰어(DoosanArmViewer)와 그 WebSocket 구독(useLiveState)이
            라우트 전환 때마다 리셋되지 않고 로봇의 실시간 움직임을 계속 따라가게 하기
            위함이다. 다른 페이지들은 평소처럼 활성 라우트일 때만 마운트한다. */}
        <div style={{ display: isHome ? undefined : "none" }}>
          <DashboardPage />
        </div>
        {otherPage}
      </div>
    </div>
  );
}
