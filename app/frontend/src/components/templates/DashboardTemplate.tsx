import type { ReactNode } from "react";

interface DashboardTemplateProps {
  orderForm: ReactNode;
  boardStock: ReactNode;
  printers: ReactNode;
  receivePos: ReactNode;
  modal?: ReactNode;
}

export function DashboardTemplate({ orderForm, boardStock, printers, receivePos, modal }: DashboardTemplateProps) {
  return (
    <div className="app">
      <main className="layout">
        {orderForm}
        {boardStock}
        {printers}
        {receivePos}
      </main>
      {modal}
    </div>
  );
}
