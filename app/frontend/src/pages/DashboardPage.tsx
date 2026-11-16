import { useState } from "react";
import { DashboardTemplate } from "../components/templates/DashboardTemplate";
import { OrderForm } from "../components/organisms/OrderForm";
import { BoardStockPanel } from "../components/organisms/BoardStockPanel";
import { BoardStockRefillModal } from "../components/organisms/BoardStockRefillModal";
import { LoadPickFailedModal } from "../components/organisms/LoadPickFailedModal";
import { useLiveState } from "../hooks/useLiveState";
import { api, WorkRequestError } from "../lib/api";
import type { Shape } from "../types";

export function DashboardPage() {
  const { alert, setAlert, loadFailedAlert, setLoadFailedAlert, boardStock } = useLiveState();
  const [orderError, setOrderError] = useState<string | null>(null);

  const handleOrder = async (customerName: string, shape: Shape) => {
    try {
      setOrderError(null);
      // 작업요청(SQS) 경로: 베드·프린터를 즉시 확인해 가능하면 SQS로 디스패치한다
      // (PRD: assets/docs/prd-work-request-sqs.md).
      await api.createWorkRequest(customerName, shape);
      return true;
    } catch (e) {
      setOrderError(e instanceof WorkRequestError ? e.message : String(e));
      return false;
    }
  };

  const handleBoardStockRefillComplete = async () => {
    await api.refillBoardStockComplete();
    setAlert(null);
  };

  const handleRetryLoad = async (workId: number) => {
    await api.retryLoad(workId);
    setLoadFailedAlert(null);
  };

  return (
    <DashboardTemplate
      orderForm={<OrderForm onOrder={handleOrder} error={orderError} />}
      boardStock={<BoardStockPanel slots={boardStock} />}
      modal={
        <>
          <BoardStockRefillModal alert={alert} onConfirm={handleBoardStockRefillComplete} />
          <LoadPickFailedModal alert={loadFailedAlert} onConfirm={handleRetryLoad} />
        </>
      }
    />
  );
}
