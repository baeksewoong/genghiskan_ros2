import { useState } from "react";
import { DashboardTemplate } from "../components/templates/DashboardTemplate";
import { OrderForm } from "../components/organisms/OrderForm";
import { BoardStockPanel } from "../components/organisms/BoardStockPanel";
import { BoardStockRefillModal } from "../components/organisms/BoardStockRefillModal";
import { LoadPickFailedModal } from "../components/organisms/LoadPickFailedModal";
import { PickupPanel } from "../components/organisms/PickupPanel";
import { PrinterPanel } from "../components/organisms/PrinterPanel";
import { useLiveState } from "../hooks/useLiveState";
import { api, WorkRequestError } from "../lib/api";
import type { Shape } from "../types";

export function DashboardPage() {
  const { alert, setAlert, loadFailedAlert, setLoadFailedAlert, boardStock, snapshot } = useLiveState();
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

  const handlePickUp = async (orderId: number) => {
    try {
      await api.pickUpOrder(orderId);
    } catch (e) {
      console.error("수령 처리 실패:", e);
    }
  };

  const handleRetryLoad = async (workId: number) => {
    // 재전송이 실패해도(예: 타임아웃으로 작업이 이미 종료됨) 모달은 닫는다 —
    // 갇힌 알럿보다는 실패를 콘솔 로그로 남기는 쪽이 낫다.
    try {
      await api.retryLoad(workId);
    } catch (e) {
      console.error("LOAD 재전송 실패:", e);
    } finally {
      setLoadFailedAlert(null);
    }
  };

  return (
    <DashboardTemplate
      orderForm={<OrderForm onOrder={handleOrder} error={orderError} />}
      boardStock={<BoardStockPanel slots={boardStock} />}
      printers={<PrinterPanel printers={snapshot?.printers ?? null} />}
      pickup={<PickupPanel orders={snapshot?.pickup_orders ?? null} onPickUp={handlePickUp} />}
      modal={
        <>
          <BoardStockRefillModal alert={alert} onConfirm={handleBoardStockRefillComplete} />
          <LoadPickFailedModal alert={loadFailedAlert} onConfirm={handleRetryLoad} />
        </>
      }
    />
  );
}
