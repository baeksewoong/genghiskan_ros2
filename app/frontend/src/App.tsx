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

  const page =
    hash === "#/sqs-monitor" ? (
      <SqsMonitorPage />
    ) : hash === "#/teaching-pendant" ? (
      <TeachingPendantPage />
    ) : hash === "#/work-history" ? (
      <WorkHistoryPage />
    ) : (
      <DashboardPage />
    );

  return (
    <div className="app-shell">
      <NavSidebar routes={ROUTES} currentPath={hash} />
      <div className="app-shell-content">{page}</div>
    </div>
  );
}
