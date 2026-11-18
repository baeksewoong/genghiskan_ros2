import { useState, type ReactNode } from "react";

export interface TabItem {
  id: string;
  label: string;
  content: ReactNode;
}

interface TabsProps {
  tabs: TabItem[];
  defaultTabId?: string;
}

/** 범용 탭 전환 UI. 콘텐츠는 각 탭이 그대로 ReactNode로 들고 있고, 이 컴포넌트는
 * 어떤 탭이 보이는지만 관리한다 — 도메인 타입을 모르는 순수 표현 컴포넌트다. */
export function Tabs({ tabs, defaultTabId }: TabsProps) {
  const [activeId, setActiveId] = useState(defaultTabId ?? tabs[0]?.id);
  const activeTab = tabs.find((tab) => tab.id === activeId) ?? tabs[0];

  return (
    <div className="tabs">
      <div className="tabs-list" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={tab.id === activeTab?.id}
            className={`tabs-tab ${tab.id === activeTab?.id ? "selected" : ""}`}
            onClick={() => setActiveId(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div className="tabs-panel" role="tabpanel">
        {activeTab?.content}
      </div>
    </div>
  );
}
