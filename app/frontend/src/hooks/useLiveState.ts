import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import type {
  BoardStockSlot,
  ReceivePos,
  Envelope,
  GripperAction,
  Order,
  StateSnapshot,
  TeachingPendantPose,
} from "../types";
import type { RobotJointsEventPayload } from "../components/organisms/DoosanArmViewer";

export interface LogEntry {
  id: string;
  ts: string;
  type: string;
  summary: string;
  data: Record<string, unknown>;
}

export interface RefillAlert {
  // 작업요청(SQS) 경로 전용: 적재대(board_stock)가 비었을 때의 알럿.
  reason: "BOARD_STOCK_EMPTY";
}

export interface LoadPickFailedAlert {
  // robot-events의 베드 집기 실패 이벤트(예: {"work_id":1,"type":"fail_load1"}) 수신 시.
  work_id: number;
}

export interface UnloadPickFailedAlert {
  // robot-events의 완성품 집기 실패 이벤트({"work_id":1,"type":"fail_unload1"}) 수신 시.
  work_id: number;
}

export interface PlaceFailedAlert {
  // robot-events의 프린터 배치 실패 이벤트({"work_id":1,"type":"fail_load2"}) 수신 시.
  work_id: number;
}

export interface ReceivePosFullAlert {
  // success_unload1 후 수령대(1, 2)가 모두 차 있어 unload2가 대기 중일 때.
  work_id: number;
}

// 티칭 팬던트(실물 로봇 조그 제어) 전용 (PRD: assets/docs/prd-teaching-pendant.md).
// 세션 상태는 DB가 아니라 서버 런타임 상태이고(5장), 프론트도 ws 이벤트로만 갱신한다
// (새로고침 시 항상 비활성으로 시작, 9장).
// lib/api.ts의 TeachingPendantError(throw되는 Error 서브클래스)와 이름이 겹치지 않도록
// 상태로 들고 있는 에러 정보는 별도 타입으로 둔다.
export interface TeachingPendantErrorInfo {
  code?: string;
  message: string;
}

export interface TeachingPendantState {
  enabled: boolean;
  owner: string | null;
  currentPose: TeachingPendantPose | null;
  // 8.2 스텝 상호 배제: 조그/그리퍼 중 하나라도 pending이면 둘 다 새 요청을 보내지 않는다.
  jogPending: boolean;
  pendingJogId: string | null;
  gripperPending: boolean;
  pendingGripperCmdId: string | null;
  gripperState: GripperAction | null;
  lastError: TeachingPendantErrorInfo | null;
}

const INITIAL_TEACHING_PENDANT_STATE: TeachingPendantState = {
  enabled: false,
  owner: null,
  currentPose: null,
  jogPending: false,
  pendingJogId: null,
  gripperPending: false,
  pendingGripperCmdId: null,
  gripperState: null,
  lastError: null,
};

function upsertOrder(snapshot: StateSnapshot, order: Order): StateSnapshot {
  const withoutOrder = (list: Order[]) => list.filter((o) => o.id !== order.id);

  const waiting_orders = withoutOrder(snapshot.waiting_orders);
  const active_orders = withoutOrder(snapshot.active_orders);
  const pickup_orders = withoutOrder(snapshot.pickup_orders);

  if (order.status === "WAITING") {
    waiting_orders.push(order);
    waiting_orders.sort((a, b) => a.created_at.localeCompare(b.created_at));
  } else if (["DISPATCHING", "LOADING", "PRINTING", "PRINT_DONE", "UNLOADING"].includes(order.status)) {
    active_orders.push(order);
  } else if (order.status === "READY_FOR_PICKUP") {
    pickup_orders.push(order);
  }
  // PICKED_UP 은 모든 목록에서 제거된 채로 끝난다.

  return { ...snapshot, waiting_orders, active_orders, pickup_orders };
}

export function summarize(type: string, data: Record<string, unknown>): string {
  switch (type) {
    case "order.created":
      return `주문 생성 #${data.id} (${data.shape})`;
    case "order.updated":
      return `주문 #${data.id} → ${data.status}`;
    case "printer.updated":
      return `프린터 ${data.slot ?? data.current_order_id} → ${data.status}`;
    case "board_stock.updated":
      return `적재대 상태 갱신`;
    case "receive_pos.updated":
      return `수령대 상태 갱신`;
    case "alert.refill_required":
      return `알럿: 보드를 채워주세요 (${data.reason})`;
    case "alert.cleared":
      return "알럿 해제";
    case "sqs.command_sent":
      return `SQS 발행 성공 (work_id=${data.work_id})`;
    case "sqs.command_failed":
      return `SQS 발행 실패 (work_id=${data.work_id})`;
    case "sqs.command_skipped":
      return `SQS 발행 건너뜀: ${data.reason}`;
    case "sqs.event_received":
      return `SQS 수신 (robot-events)`;
    case "sqs.event_parse_error":
      return `SQS 메시지 파싱 실패`;
    case "alert.load_pick_failed":
      return `알럿: 베드 집기 실패 (work_id=${data.work_id})`;
    case "alert.unload_pick_failed":
      return `알럿: 완성품 집기 실패 (work_id=${data.work_id})`;
    case "alert.place_failed":
      return `알럿: 프린터 배치 실패 (work_id=${data.work_id})`;
    case "alert.receive_pos_full":
      return `알럿: 수령대 가득 참 (work_id=${data.work_id})`;
    case "alert.receive_pos_full_cleared":
      return `수령대 자리 확보 → unload2 발행 (work_id=${data.work_id})`;
    case "teaching_pendant.session_changed":
      return `티칭 팬던트 세션 ${data.enabled ? `활성화 (소유자: ${data.owner})` : "비활성화"}`;
    case "teaching_pendant.jog_completed":
      return `조그 완료 (jog_id=${data.jog_id})`;
    case "teaching_pendant.jog_failed":
      return `조그 실패 (jog_id=${data.jog_id}): ${data.error_code}`;
    case "teaching_pendant.gripper_completed":
      return `그리퍼 ${data.state} 완료 (gripper_cmd_id=${data.gripper_cmd_id})`;
    case "teaching_pendant.gripper_failed":
      return `그리퍼 명령 실패 (gripper_cmd_id=${data.gripper_cmd_id}): ${data.error_code}`;
    case "robot.joints_updated":
      return `로봇 관절각 갱신 (robot_id=${data.robot_id})`;
    default:
      return type;
  }
}

export function useLiveState() {
  const [snapshot, setSnapshot] = useState<StateSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [alert, setAlert] = useState<RefillAlert | null>(null);
  const [loadFailedAlert, setLoadFailedAlert] = useState<LoadPickFailedAlert | null>(null);
  const [unloadFailedAlert, setUnloadFailedAlert] = useState<UnloadPickFailedAlert | null>(null);
  const [placeFailedAlert, setPlaceFailedAlert] = useState<PlaceFailedAlert | null>(null);
  const [receivePosFullAlert, setReceivePosFullAlert] = useState<ReceivePosFullAlert | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);
  // SQS 모니터링 페이지 전용: 다른 이벤트에 밀려 log(50개 캡)에서
  // 잘려나가지 않도록 sqs.* 이벤트만 따로 쌓아둔다.
  const [sqsLog, setSqsLog] = useState<LogEntry[]>([]);
  // 적재대(board_stock) 현황 — home의 적재대 현황 UI 전용.
  const [boardStock, setBoardStock] = useState<BoardStockSlot[] | null>(null);
  // 수령대(receive_pos) 현황 — home의 수령대 현황 UI 전용.
  const [receivePos, setReceivePos] = useState<ReceivePos[] | null>(null);
  // 티칭 팬던트 페이지 전용.
  const [teachingPendant, setTeachingPendant] = useState<TeachingPendantState>(INITIAL_TEACHING_PENDANT_STATE);
  // 실물 로봇의 실시간 관절각(약 10Hz) — 티칭 팬던트 3D 뷰어 전용. log(50개 캡)에
  // 넣으면 금방 다른 이벤트를 밀어내므로 별도 state로만 둔다.
  const [robotJoints, setRobotJoints] = useState<RobotJointsEventPayload | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/ws/client`);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!cancelled) retryTimer = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws.close();

      ws.onmessage = (event) => {
        const envelope: Envelope<Record<string, unknown>> = JSON.parse(event.data);

        // robot.joints_updated는 ~10Hz로 쏟아져 log(50개 캡)를 순식간에 밀어내므로
        // 로그 적재 없이 state만 갱신한다 (event_logs DB에도 안 쌓이는 이벤트).
        if (envelope.type === "robot.joints_updated") {
          setRobotJoints(envelope.data as unknown as RobotJointsEventPayload);
          return;
        }

        const entry: LogEntry = {
          id: envelope.event_id,
          ts: envelope.ts,
          type: envelope.type,
          summary: summarize(envelope.type, envelope.data),
          data: envelope.data,
        };
        setLog((prev) => [entry, ...prev].slice(0, 50));
        if (envelope.type.startsWith("sqs.")) {
          setSqsLog((prev) => [entry, ...prev].slice(0, 200));
        }

        setSnapshot((prev) => {
          if (envelope.type === "state.snapshot") {
            return envelope.data as unknown as StateSnapshot;
          }
          if (!prev) return prev;

          switch (envelope.type) {
            case "order.created":
            case "order.updated":
              return upsertOrder(prev, envelope.data as unknown as Order);
            case "printer.updated": {
              const printers = prev.printers.map((p) =>
                p.slot === (envelope.data as any).slot ? { ...p, ...(envelope.data as any) } : p
              );
              return { ...prev, printers };
            }
            default:
              return prev;
          }
        });

        if (envelope.type === "alert.refill_required") {
          setAlert({ reason: (envelope.data as any).reason });
        } else if (envelope.type === "alert.cleared") {
          setAlert(null);
        } else if (envelope.type === "alert.load_pick_failed") {
          setLoadFailedAlert({ work_id: (envelope.data as any).work_id });
        } else if (envelope.type === "alert.unload_pick_failed") {
          setUnloadFailedAlert({ work_id: (envelope.data as any).work_id });
        } else if (envelope.type === "alert.place_failed") {
          setPlaceFailedAlert({ work_id: (envelope.data as any).work_id });
        } else if (envelope.type === "alert.receive_pos_full") {
          setReceivePosFullAlert({ work_id: (envelope.data as any).work_id });
        } else if (envelope.type === "alert.receive_pos_full_cleared") {
          const workId = (envelope.data as any).work_id;
          setReceivePosFullAlert((prev) => (prev && prev.work_id === workId ? null : prev));
        } else if (envelope.type === "board_stock.updated") {
          const slots = (envelope.data as any).slots as { slot: number; status: BoardStockSlot["status"] }[];
          setBoardStock((prev) => {
            const base: BoardStockSlot[] = prev ?? slots.map((s) => ({ ...s, updated_at: "" }));
            return base.map((s) => {
              const match = slots.find((x) => x.slot === s.slot);
              return match ? { ...s, status: match.status } : s;
            });
          });
        } else if (envelope.type === "receive_pos.updated") {
          // 서버가 수령대 전체(1, 2) 스냅샷을 보내므로 통째로 교체한다.
          const positions = (envelope.data as any).positions as Omit<ReceivePos, "updated_at">[];
          setReceivePos(positions.map((p) => ({ ...p, updated_at: envelope.ts })));
        } else if (envelope.type === "teaching_pendant.session_changed") {
          const data = envelope.data as { enabled: boolean; owner?: string | null };
          setTeachingPendant({ ...INITIAL_TEACHING_PENDANT_STATE, enabled: data.enabled, owner: data.owner ?? null });
        } else if (envelope.type === "teaching_pendant.jog_completed") {
          const data = envelope.data as { jog_id: string; current_pose: TeachingPendantPose };
          setTeachingPendant((prev) => {
            if (data.jog_id !== prev.pendingJogId) return prev; // 알 수 없는 jog_id는 무시 (8장)
            return { ...prev, currentPose: data.current_pose, jogPending: false, pendingJogId: null, lastError: null };
          });
        } else if (envelope.type === "teaching_pendant.jog_failed") {
          const data = envelope.data as { jog_id: string; error_code: string };
          setTeachingPendant((prev) => {
            if (data.jog_id !== prev.pendingJogId) return prev;
            return {
              ...prev,
              jogPending: false,
              pendingJogId: null,
              lastError: { code: data.error_code, message: `조그 실패: ${data.error_code}` },
            };
          });
        } else if (envelope.type === "teaching_pendant.gripper_completed") {
          const data = envelope.data as { gripper_cmd_id: string; state: GripperAction };
          setTeachingPendant((prev) => {
            if (data.gripper_cmd_id !== prev.pendingGripperCmdId) return prev;
            return {
              ...prev,
              gripperState: data.state,
              gripperPending: false,
              pendingGripperCmdId: null,
              lastError: null,
            };
          });
        } else if (envelope.type === "teaching_pendant.gripper_failed") {
          const data = envelope.data as { gripper_cmd_id: string; error_code: string };
          setTeachingPendant((prev) => {
            if (data.gripper_cmd_id !== prev.pendingGripperCmdId) return prev;
            return {
              ...prev,
              gripperPending: false,
              pendingGripperCmdId: null,
              lastError: { code: data.error_code, message: `그리퍼 명령 실패: ${data.error_code}` },
            };
          });
        }
      };
    }

    api.getState().then(setSnapshot).catch(() => undefined);
    api.getBoardStock().then(setBoardStock).catch(() => undefined);
    api.getReceivePos().then(setReceivePos).catch(() => undefined);
    connect();

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      wsRef.current?.close();
    };
  }, []);

  // 아래 함수들은 티칭 팬던트 페이지 전용 — REST 요청을 보낸 "직후"(page가 호출) 또는
  // 클라이언트 쪽 타임아웃(TP-11) 발생 시 세션 상태를 갱신한다. 실제 완료/실패는 여전히
  // 위 ws.onmessage의 teaching_pendant.* 이벤트가 갱신한다.

  /** POST /session 응답을 즉시 반영한다 — WS 브로드캐스트(teaching_pendant.session_changed)가
   * 재연결 타이밍 등으로 이 클라이언트에 도달하지 못해도 활성화/비활성화 버튼이 서버 상태와
   * 어긋나지 않도록 REST 응답 자체를 신뢰한다. 뒤이어 같은 내용의 WS 이벤트가 와도 멱등이라
   * 문제 없다. */
  function applyTeachingPendantSession(enabled: boolean, currentPose: TeachingPendantPose | null) {
    setTeachingPendant((prev) => ({
      ...INITIAL_TEACHING_PENDANT_STATE,
      enabled,
      currentPose,
      owner: enabled ? prev.owner : null,
    }));
  }

  /** POST /jog가 202로 받아들여진 직후 호출 — 다음 완료/실패 응답이 올 때까지
   * 조그 패드를 막는다(8.2 스텝 상호 배제). */
  function beginTeachingPendantJog(jogId: string) {
    setTeachingPendant((prev) => ({ ...prev, jogPending: true, pendingJogId: jogId, lastError: null }));
  }

  function beginTeachingPendantGripper(cmdId: string) {
    setTeachingPendant((prev) => ({ ...prev, gripperPending: true, pendingGripperCmdId: cmdId, lastError: null }));
  }

  /** TP-11 세션 타임아웃: 일정 시간 내 완료/실패 응답이 없으면 에러를 띄우고 운영자
   * 확인을 요구한다. pending은 그대로 둬 로봇이 실제로 움직이고 있을 가능성에 대해
   * 섣불리 "끝났다"고 가정하지 않는다 — acknowledgeTeachingPendantError()로만 풀린다. */
  function timeoutTeachingPendantJog(jogId: string) {
    setTeachingPendant((prev) => {
      if (jogId !== prev.pendingJogId) return prev;
      return {
        ...prev,
        lastError: { code: "TIMEOUT", message: "조그 응답 시간 초과 — 로봇 상태를 직접 확인한 뒤 확인을 눌러주세요." },
      };
    });
  }

  function timeoutTeachingPendantGripper(cmdId: string) {
    setTeachingPendant((prev) => {
      if (cmdId !== prev.pendingGripperCmdId) return prev;
      return {
        ...prev,
        lastError: { code: "TIMEOUT", message: "그리퍼 응답 시간 초과 — 로봇 상태를 직접 확인한 뒤 확인을 눌러주세요." },
      };
    });
  }

  /** 세션 활성화 요청(동기 4xx) 등, ws 이벤트가 아니라 REST 응답 자체에서 바로 알게 되는
   * 에러를 표시한다 (jog_id/gripper_cmd_id가 아직 없는 거부 — 8.2 "세션이 비활성 상태"
   * 409 등). */
  function reportTeachingPendantError(message: string, code?: string) {
    setTeachingPendant((prev) => ({ ...prev, lastError: { code, message } }));
  }

  /** 타임아웃 에러를 운영자가 확인했을 때 — pending을 강제로 풀어 버튼을 다시 쓸 수
   * 있게 한다. */
  function acknowledgeTeachingPendantError() {
    setTeachingPendant((prev) => ({
      ...prev,
      lastError: null,
      jogPending: false,
      pendingJogId: null,
      gripperPending: false,
      pendingGripperCmdId: null,
    }));
  }

  return {
    snapshot,
    connected,
    alert,
    loadFailedAlert,
    unloadFailedAlert,
    placeFailedAlert,
    receivePosFullAlert,
    log,
    sqsLog,
    setAlert,
    setLoadFailedAlert,
    setUnloadFailedAlert,
    setPlaceFailedAlert,
    setReceivePosFullAlert,
    boardStock,
    receivePos,
    teachingPendant,
    robotJoints,
    applyTeachingPendantSession,
    beginTeachingPendantJog,
    beginTeachingPendantGripper,
    timeoutTeachingPendantJog,
    timeoutTeachingPendantGripper,
    reportTeachingPendantError,
    acknowledgeTeachingPendantError,
  };
}
