import type { ReactNode } from "react";
import { Clock } from "../atoms/Clock";

interface DashboardTemplateProps {
  orderForm: ReactNode;
  boardStock: ReactNode;
  printers: ReactNode;
  receivePos: ReactNode;
  waitingQueue: ReactNode;
  /** 로봇 팔 3D 뷰어(DoosanArmViewer) — 티칭 팬던트 페이지에서 옮겨와 홈에서도
   * 로봇의 실시간 움직임을 보여준다 (App.tsx가 라우트 전환에도 이 페이지를
   * 언마운트하지 않으므로 뷰어 연결/상태가 계속 유지된다). */
  armViewer: ReactNode;
  modal?: ReactNode;
}

/** 홈 화면(키오스크) 레이아웃. 매장 브랜딩/시계 헤더 아래를 좌우 2단으로 나눠,
 * 왼쪽에는 로봇 3D 뷰어(실시간 상태)를, 오른쪽에는 작업요청 히어로 + 적재대/작업대/
 * 수령대 현황판 + 작업 대기 중 큐 등 나머지 키오스크 UI를 세로로 쌓아 배치한다.
 * 데이터/상태는 전혀 소유하지 않고 ReactNode만 꽂아 넣는 순수 레이아웃. */
export function DashboardTemplate({
  orderForm,
  boardStock,
  printers,
  receivePos,
  waitingQueue,
  armViewer,
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
        <section className="kiosk-robot-column">{armViewer}</section>
        <div className="kiosk-content-column">
          <section className="kiosk-hero">{orderForm}</section>
          <section className="kiosk-status-board">
            {boardStock}
            {printers}
            {receivePos}
          </section>
          {waitingQueue}
        </div>
      </main>
      {modal}
    </div>
  );
}
