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

const NAV_OPEN_STORAGE_KEY = "genghiskan.nav-open";

/** 네비게이션 토글 상태를 localStorage에 저장해, 운영자가 접어둔 채로 새로고침해도
 * 키오스크 화면 공간을 다시 뺏기지 않게 한다. */
function loadNavOpen(): boolean {
  try {
    return localStorage.getItem(NAV_OPEN_STORAGE_KEY) !== "0";
  } catch {
    return true;
  }
}

export default function App() {
  const [hash, setHash] = useState(normalizeHash(location.hash));
  const [navOpen, setNavOpen] = useState(loadNavOpen);

  useEffect(() => {
    const onHashChange = () => setHash(normalizeHash(location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(NAV_OPEN_STORAGE_KEY, navOpen ? "1" : "0");
    } catch {
      // 프라이빗 모드 등 저장 불가 시 무시 — 토글 상태는 이번 세션 동안만 유지된다.
    }
  }, [navOpen]);

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
      <NavSidebar routes={ROUTES} currentPath={hash} open={navOpen} onToggle={() => setNavOpen((v) => !v)} />
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
