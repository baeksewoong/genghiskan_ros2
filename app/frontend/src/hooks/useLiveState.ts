import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import type { BoardStockSlot, Envelope, Order, SimulatorSettings, StateSnapshot } from "../types";
import type { TaskType } from "../lib/robotArm";

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

export interface FeedbackEvent {
  task_id: number;
  type: TaskType;
  slot: number;
  phase: string;
  progress: number;
}

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

function summarize(type: string, data: Record<string, unknown>): string {
  switch (type) {
    case "order.created":
      return `주문 생성 #${data.id} (${data.shape})`;
    case "order.updated":
      return `주문 #${data.id} → ${data.status}`;
    case "printer.updated":
      return `프린터 ${data.slot ?? data.current_order_id} → ${data.status}`;
    case "board_stock.updated":
      return `적재대 상태 갱신`;
    case "robot.state":
      return `로봇 상태 → ${data.state}`;
    case "robot.feedback":
      return `로봇 작업 ${data.task_id} 단계 ${data.phase}`;
    case "alert.refill_required":
      return `알럿: 보드를 채워주세요 (${data.reason})`;
    case "alert.cleared":
      return "알럿 해제";
    case "bridge.connection":
      return `로봇 연결 ${data.connected ? "됨" : "끊김"}`;
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
    default:
      return type;
  }
}

export function useLiveState() {
  const [snapshot, setSnapshot] = useState<StateSnapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const [alert, setAlert] = useState<RefillAlert | null>(null);
  const [loadFailedAlert, setLoadFailedAlert] = useState<LoadPickFailedAlert | null>(null);
  const [log, setLog] = useState<LogEntry[]>([]);
  // SQS 모니터링 페이지 전용: 다른 이벤트(robot.state 하트비트 등)에 밀려 log(50개 캡)에서
  // 잘려나가지 않도록 sqs.* 이벤트만 따로 쌓아둔다.
  const [sqsLog, setSqsLog] = useState<LogEntry[]>([]);
  const [feedback, setFeedback] = useState<FeedbackEvent | null>(null);
  // 적재대(board_stock) 현황 — home의 적재대 현황 UI 전용.
  const [boardStock, setBoardStock] = useState<BoardStockSlot[] | null>(null);
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
            case "robot.state":
              return {
                ...prev,
                robot: { ...prev.robot, state: (envelope.data as any).state, current_task_id: (envelope.data as any).current_task_id },
              };
            case "bridge.connection":
              return { ...prev, robot: { ...prev.robot, bridge_connected: (envelope.data as any).connected } };
            default:
              return prev;
          }
        });

        if (envelope.type === "robot.feedback") {
          setFeedback(envelope.data as unknown as FeedbackEvent);
        } else if (envelope.type === "alert.refill_required") {
          setAlert({ reason: (envelope.data as any).reason });
        } else if (envelope.type === "alert.cleared") {
          setAlert(null);
        } else if (envelope.type === "alert.load_pick_failed") {
          setLoadFailedAlert({ work_id: (envelope.data as any).work_id });
        } else if (envelope.type === "board_stock.updated") {
          const slots = (envelope.data as any).slots as { slot: number; status: BoardStockSlot["status"] }[];
          setBoardStock((prev) => {
            const base: BoardStockSlot[] = prev ?? slots.map((s) => ({ ...s, updated_at: "" }));
            return base.map((s) => {
              const match = slots.find((x) => x.slot === s.slot);
              return match ? { ...s, status: match.status } : s;
            });
          });
        }
      };
    }

    api.getState().then(setSnapshot).catch(() => undefined);
    api.getBoardStock().then(setBoardStock).catch(() => undefined);
    connect();

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
      wsRef.current?.close();
    };
  }, []);

  function updateSimulator(patch: Partial<SimulatorSettings>) {
    setSnapshot((prev) => (prev ? { ...prev, simulator: { ...prev.simulator, ...patch } } : prev));
  }

  return {
    snapshot,
    connected,
    alert,
    loadFailedAlert,
    log,
    sqsLog,
    setAlert,
    setLoadFailedAlert,
    feedback,
    updateSimulator,
    boardStock,
  };
}
