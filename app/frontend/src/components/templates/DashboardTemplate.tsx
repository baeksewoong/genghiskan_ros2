import type { ReactNode } from "react";

interface DashboardTemplateProps {
  orderForm: ReactNode;
  boardStock: ReactNode;
  modal?: ReactNode;
}

export function DashboardTemplate({ orderForm, boardStock, modal }: DashboardTemplateProps) {
  return (
    <div className="app">
      <main className="layout">
        {orderForm}
        {boardStock}
      </main>
      {modal}
    </div>
  );
}
