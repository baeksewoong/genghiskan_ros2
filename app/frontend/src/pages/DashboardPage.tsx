import { useState } from "react";
import { DashboardTemplate } from "../components/templates/DashboardTemplate";
import { OrderForm } from "../components/organisms/OrderForm";
import { BoardStockPanel } from "../components/organisms/BoardStockPanel";
import { BoardStockRefillModal } from "../components/organisms/BoardStockRefillModal";
import { LoadPickFailedModal } from "../components/organisms/LoadPickFailedModal";
import { UnloadPickFailedModal } from "../components/organisms/UnloadPickFailedModal";
import { PlaceFailedModal } from "../components/organisms/PlaceFailedModal";
import { AdminContactModal } from "../components/organisms/AdminContactModal";
import { ReceivePosFullModal } from "../components/organisms/ReceivePosFullModal";
import { ReceivePosPanel } from "../components/organisms/ReceivePosPanel";
import { PrinterPanel } from "../components/organisms/PrinterPanel";
import { OrderQueuePanel } from "../components/organisms/OrderQueuePanel";
import { useLiveState } from "../hooks/useLiveState";
import { api, WorkRequestError } from "../lib/api";
import type { Shape } from "../types";

export function DashboardPage() {
  const {
    alert,
    setAlert,
    loadFailedAlert,
    setLoadFailedAlert,
    unloadFailedAlert,
    setUnloadFailedAlert,
    placeFailedAlert,
    setPlaceFailedAlert,
    receivePosFullAlert,
    setReceivePosFullAlert,
    boardStock,
    receivePos,
    snapshot,
  } = useLiveState();
  const [orderError, setOrderError] = useState<string | null>(null);
  const [adminContactOpen, setAdminContactOpen] = useState(false);

  // 수령대 칸에 올라간 주문 상세 조회용: 이동 중(UNLOADING)은 active, 수령 대기는 pickup에 있다.
  const receiveOrders = [...(snapshot?.active_orders ?? []), ...(snapshot?.pickup_orders ?? [])];

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

  const handleRetryUnload = async (workId: number) => {
    // handleRetryLoad와 동일: 재전송이 실패해도 모달은 닫고 콘솔에 남긴다.
    try {
      await api.retryUnload(workId);
    } catch (e) {
      console.error("UNLOAD 재전송 실패:", e);
    } finally {
      setUnloadFailedAlert(null);
    }
  };

  const handleConfirmPlaceYes = async (workId: number) => {
    // handleRetryLoad와 동일: 전송이 실패해도 모달은 닫고 콘솔에 남긴다.
    try {
      await api.confirmPlace(workId);
    } catch (e) {
      console.error("배치 확인 전송 실패:", e);
    } finally {
      setPlaceFailedAlert(null);
    }
  };

  const handleConfirmPlaceNo = () => {
    setPlaceFailedAlert(null);
    setAdminContactOpen(true);
  };

  return (
    <DashboardTemplate
      orderForm={<OrderForm onOrder={handleOrder} error={orderError} />}
      boardStock={<BoardStockPanel slots={boardStock} />}
      printers={<PrinterPanel printers={snapshot?.printers ?? null} />}
      receivePos={<ReceivePosPanel positions={receivePos} orders={receiveOrders} onPickUp={handlePickUp} />}
      waitingQueue={
        <OrderQueuePanel
          icon="🕒"
          title="작업 대기 중"
          orders={snapshot?.waiting_orders ?? []}
          emptyLabel="대기 중인 주문이 없습니다."
        />
      }
      modal={
        <>
          <BoardStockRefillModal alert={alert} onConfirm={handleBoardStockRefillComplete} />
          <LoadPickFailedModal alert={loadFailedAlert} onConfirm={handleRetryLoad} />
          <UnloadPickFailedModal alert={unloadFailedAlert} onConfirm={handleRetryUnload} />
          <PlaceFailedModal alert={placeFailedAlert} onYes={handleConfirmPlaceYes} onNo={handleConfirmPlaceNo} />
          <AdminContactModal open={adminContactOpen} onClose={() => setAdminContactOpen(false)} />
          <ReceivePosFullModal alert={receivePosFullAlert} onClose={() => setReceivePosFullAlert(null)} />
        </>
      }
    />
  );
}
