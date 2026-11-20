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
import { DoosanM0609Viewer } from "../components/organisms/DoosanArmViewer/DoosanArmViewer";
import { DOOSAN_HOME_POSES_DEG } from "../components/organisms/DoosanArmViewer";
import { useLiveState } from "../hooks/useLiveState";
import { api, WorkRequestError } from "../lib/api";
import type { Shape } from "../types";

/** 홈(키오스크) 페이지. 티칭 팬던트 페이지에 있던 3D 뷰어를 이곳으로 옮겨와
 * 매장에서도 로봇의 실시간 움직임을 볼 수 있게 한다. App.tsx가 이 페이지를
 * 다른 라우트로 이동해도 언마운트하지 않고 CSS로만 숨기므로, 여기서 구독하는
 * useLiveState()의 WebSocket 연결과 robotJoints 상태가 라우트 전환에도 그대로
 * 유지된다(뷰어가 리셋되지 않음). */
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
    connected,
    robotJoints,
  } = useLiveState();
  const [orderError, setOrderError] = useState<string | null>(null);
  const [adminContactOpen, setAdminContactOpen] = useState(false);

  // 수령대 칸에 올라간 주문 상세 조회용: 이동 중(UNLOADING)은 active, 수령 대기는 pickup에 있다.
  const receiveOrders = [...(snapshot?.active_orders ?? []), ...(snapshot?.pickup_orders ?? [])];

  // 실시간 관절각: robot.joints_updated(약 10Hz, ROS2 브릿지)가 있으면 그걸 쓰고, 아직
  // 없으면(연결 직후 등) 두산 표준 홈(ready) 자세를 기본값으로 보여준다. 홈 화면은 조그 제어가
  // 없으므로 teaching_pendant.currentPose는 참조하지 않는다(티칭 팬던트 페이지 전용).
  const liveJoints = robotJoints ? robotJoints.joints : DOOSAN_HOME_POSES_DEG.ready;
  const liveAngleUnit = robotJoints ? robotJoints.angle_unit : "deg";
  const liveTimestampMs = robotJoints ? robotJoints.timestamp_ms : undefined;
  const viewerConnectionStatus = connected ? "connected" : "disconnected";

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
      armViewer={
        <section className="panel kiosk-card arm-viewer-panel">
          <h2>
            <span className="kiosk-card-icon" aria-hidden="true">
              🦾
            </span>
            로봇 실시간 상태
          </h2>
          <DoosanM0609Viewer
            assetsBaseUrl="/assets/doosan/m0609_rg2"
            gripper="rg2"
            joints={liveJoints}
            angleUnit={liveAngleUnit}
            timestampMs={liveTimestampMs}
            connectionStatus={viewerConnectionStatus}
            showHomeButton={false}
            showGripperControls={false}
          />
        </section>
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
