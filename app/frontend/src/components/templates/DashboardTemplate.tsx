import type { ReactNode } from "react";

interface DashboardTemplateProps {
  orderForm: ReactNode;
  boardStock: ReactNode;
  printers: ReactNode;
  pickup: ReactNode;
  modal?: ReactNode;
}

export function DashboardTemplate({ orderForm, boardStock, printers, pickup, modal }: DashboardTemplateProps) {
  return (
    <div className="app">
      <main className="layout">
        {orderForm}
        {boardStock}
        {printers}
        {pickup}
      </main>
      {modal}
    </div>
  );
}
