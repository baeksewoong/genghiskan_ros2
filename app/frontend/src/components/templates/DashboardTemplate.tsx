import type { ReactNode } from "react";
import { Clock } from "../atoms/Clock";

interface DashboardTemplateProps {
  orderForm: ReactNode;
  boardStock: ReactNode;
  printers: ReactNode;
  receivePos: ReactNode;
  modal?: ReactNode;
}

/** 홈 화면(키오스크) 레이아웃. 매장 브랜딩/시계 헤더 + 작업요청 히어로 +
 * 적재대/작업대/수령대 현황판을 화면 전체를 채우는 하나의 키오스크로 배치한다.
 * 데이터/상태는 전혀 소유하지 않고 ReactNode만 꽂아 넣는 순수 레이아웃. */
export function DashboardTemplate({
  orderForm,
  boardStock,
  printers,
  receivePos,
  modal,
}: DashboardTemplateProps) {
  return (
    <div className="app kiosk">
      <header className="kiosk-header">
        <div className="kiosk-brand">
          <span className="kiosk-brand-icon" aria-hidden="true">
            🖨️
          </span>
          <div className="kiosk-brand-text">
            <h1>Genghiskan 3D 프린트 스토어</h1>
            <p>무인 셀프 3D 프린팅 키오스크</p>
          </div>
        </div>
        <Clock />
      </header>
      <main className="kiosk-main">
        <section className="kiosk-hero">{orderForm}</section>
        <section className="kiosk-status-board">
          {boardStock}
          {printers}
          {receivePos}
        </section>
      </main>
      {modal}
    </div>
  );
}
