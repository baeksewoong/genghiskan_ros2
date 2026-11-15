import type { ReactNode } from "react";

interface DashboardTemplateProps {
  topBar: ReactNode;
  waitingQueue: ReactNode;
  activeQueue: ReactNode;
  pickupQueue: ReactNode;
  orderForm: ReactNode;
  debugPanel: ReactNode;
  eventLogPanel: ReactNode;
  modal?: ReactNode;
}

export function DashboardTemplate({
  topBar,
  waitingQueue,
  activeQueue,
  pickupQueue,
  orderForm,
  debugPanel,
  eventLogPanel,
  modal,
}: DashboardTemplateProps) {
  return (
    <div className="app">
      {topBar}
      <main className="layout">
        {waitingQueue}
        {activeQueue}
        {pickupQueue}
        {orderForm}
        {debugPanel}
        {eventLogPanel}
      </main>
      {modal}
    </div>
  );
}
