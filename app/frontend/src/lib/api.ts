import type { BoardStockSlot, Envelope, Order, Shape, SimulatorSettings, SqsStatus, StateSnapshot } from "../types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    throw new Error(`${init?.method ?? "GET"} ${path} failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/** 작업요청(SQS) 경로 전용: 서버가 {"detail": {error_code, message, order_id}} 형태로
 * 돌려주는 에러(409 베드 없음, 502 SQS 전송 실패 등)를 그대로 담아 던진다
 * (PRD: assets/docs/prd-work-request-sqs.md 6장). */
export class WorkRequestError extends Error {
  errorCode?: string;
  orderId?: number;

  constructor(message: string, errorCode?: string, orderId?: number) {
    super(message);
    this.errorCode = errorCode;
    this.orderId = orderId;
  }
}

async function createWorkRequest(customerName: string, shape: Shape): Promise<Order> {
  const res = await fetch("/api/work-requests", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ shape, customer_name: customerName || null }),
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body?.detail as { error_code?: string; message?: string; order_id?: number } | undefined;
    throw new WorkRequestError(
      detail?.message ?? `작업요청 실패: ${res.status}`,
      detail?.error_code,
      detail?.order_id
    );
  }
  return body as Order;
}

async function retryLoad(workId: number): Promise<void> {
  const res = await fetch(`/api/work-requests/${workId}/retry-load`, { method: "POST" });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body?.detail as { error_code?: string; message?: string } | undefined;
    throw new WorkRequestError(detail?.message ?? `재시도 실패: ${res.status}`, detail?.error_code);
  }
}

async function pickUpOrder(orderId: number): Promise<Order> {
  return request<Order>(`/api/orders/${orderId}/pickup`, { method: "POST" });
}

export const api = {
  getState: () => request<StateSnapshot>("/api/state"),

  createOrder: (customerName: string, shape: Shape) =>
    request<Order>("/api/orders", {
      method: "POST",
      body: JSON.stringify({ shape, customer_name: customerName || null }),
    }),

  // 작업요청(SQS) 경로 전용 (PRD: assets/docs/prd-work-request-sqs.md).
  createWorkRequest,

  getBoardStock: () => request<BoardStockSlot[]>("/api/board-stock"),

  refillBoardStockComplete: () =>
    request<BoardStockSlot[]>("/api/board-stock/refill-complete", { method: "POST" }),

  getSimulator: () => request<SimulatorSettings>("/api/simulator"),

  patchSimulator: (patch: Partial<SimulatorSettings>) =>
    request<SimulatorSettings>("/api/simulator", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  setDebugFault: (kind: "NO_BOARD" | "GRIP_FAIL") =>
    request("/api/debug/faults", {
      method: "PATCH",
      body: JSON.stringify({ kind, once: true }),
    }),

  // SQS 모니터링 페이지 전용: 큐 깊이(ApproximateNumberOfMessages 등)만 조회한다.
  getSqsStatus: () => request<SqsStatus>("/api/sqs/status"),

  // SQS 모니터링 페이지 전용: event_logs에 저장된 과거 sqs.* 메시지 히스토리(최신순).
  getSqsHistory: (limit = 200) =>
    request<Envelope<Record<string, unknown>>[]>(`/api/sqs/history?limit=${limit}`),

  // 베드 집기 실패 알럿("확인") 전용: 같은 work_id로 LOAD 명령을 SQS에 재전송한다.
  retryLoad,

  // 수령대 "수령하기" 버튼 전용: 눌렀을 때만 주문을 수령대에서 내린다.
  pickUpOrder,
};
