import type { ReactNode } from "react";

interface DashboardTemplateProps {
  armViewer: ReactNode;
  orderForm: ReactNode;
  boardStock: ReactNode;
  printers: ReactNode;
  receivePos: ReactNode;
  modal?: ReactNode;
}

export function DashboardTemplate({
  armViewer,
  orderForm,
  boardStock,
  printers,
  receivePos,
  modal,
}: DashboardTemplateProps) {
  return (
    <div className="app">
      <main className="layout">
        {armViewer}
        {orderForm}
        {boardStock}
        {printers}
        {receivePos}
      </main>
      {modal}
    </div>
  );
}
