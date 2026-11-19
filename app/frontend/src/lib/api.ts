import type {
  BoardStockSlot,
  ReceivePos,
  Envelope,
  GripperAction,
  JogAxis,
  JogDirection,
  JogRefFrame,
  JogSpace,
  Order,
  OrderStatus,
  Shape,
  SqsStatus,
  StateSnapshot,
  TeachingPendantPose,
} from "../types";

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

async function retryUnload(workId: number): Promise<void> {
  const res = await fetch(`/api/work-requests/${workId}/retry-unload`, { method: "POST" });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body?.detail as { error_code?: string; message?: string } | undefined;
    throw new WorkRequestError(detail?.message ?? `재시도 실패: ${res.status}`, detail?.error_code);
  }
}

async function confirmPlace(workId: number): Promise<void> {
  const res = await fetch(`/api/work-requests/${workId}/confirm-place`, { method: "POST" });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body?.detail as { error_code?: string; message?: string } | undefined;
    throw new WorkRequestError(detail?.message ?? `배치 확인 실패: ${res.status}`, detail?.error_code);
  }
}

async function pickUpOrder(orderId: number): Promise<Order> {
  return request<Order>(`/api/orders/${orderId}/pickup`, { method: "POST" });
}

/** 티칭 팬던트(실물 로봇 조그 제어) 전용: 서버가 {"detail": {error_code, message}}
 * (또는 평평한 {error_code, message}) 형태로 돌려주는 에러(세션 활성화 거부, 409 등)를
 * 그대로 담아 던진다 (PRD: assets/docs/prd-teaching-pendant.md 6장). */
export class TeachingPendantError extends Error {
  errorCode?: string;

  constructor(message: string, errorCode?: string) {
    super(message);
    this.errorCode = errorCode;
  }
}

async function teachingPendantRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = (body?.detail ?? body) as { error_code?: string; message?: string } | undefined;
    throw new TeachingPendantError(
      detail?.message ?? `${init?.method ?? "GET"} ${path} 실패: ${res.status}`,
      detail?.error_code
    );
  }
  return body as T;
}

interface TeachingPendantSessionResponse {
  enabled: boolean;
  current_pose?: TeachingPendantPose;
}

function setTeachingPendantSession(enable: boolean): Promise<TeachingPendantSessionResponse> {
  return teachingPendantRequest<TeachingPendantSessionResponse>("/api/teaching-pendant/session", {
    method: "POST",
    body: JSON.stringify({ enable }),
  });
}

interface JogRequestBody {
  space: JogSpace;
  ref_frame?: JogRefFrame;
  axis: JogAxis;
  direction: JogDirection;
  step_size: number;
}

export const api = {
  getState: () => request<StateSnapshot>("/api/state"),

  // 작업요청(SQS) 경로 전용 (PRD: assets/docs/prd-work-request-sqs.md).
  createWorkRequest,

  // 작업 히스토리 페이지 전용: 전체 주문 목록(서버가 created_at 내림차순으로 반환).
  getOrders: (params?: { status?: OrderStatus; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.status) query.set("status", params.status);
    if (params?.limit) query.set("limit", String(params.limit));
    const qs = query.toString();
    return request<Order[]>(`/api/orders${qs ? `?${qs}` : ""}`);
  },

  getBoardStock: () => request<BoardStockSlot[]>("/api/board-stock"),
  getReceivePos: () => request<ReceivePos[]>("/api/receive-pos"),

  refillBoardStockComplete: () =>
    request<BoardStockSlot[]>("/api/board-stock/refill-complete", { method: "POST" }),

  // SQS 모니터링 페이지 전용: 큐 깊이(ApproximateNumberOfMessages 등)만 조회한다.
  getSqsStatus: () => request<SqsStatus>("/api/sqs/status"),

  // SQS 모니터링 페이지 전용: event_logs에 저장된 과거 sqs.* 메시지 히스토리(최신순).
  getSqsHistory: (limit = 200) =>
    request<Envelope<Record<string, unknown>>[]>(`/api/sqs/history?limit=${limit}`),

  // 베드 집기 실패 알럿("확인") 전용: 같은 work_id로 LOAD 명령을 SQS에 재전송한다.
  retryLoad,
  retryUnload,

  // 프린터 배치 실패 알럿("네") 전용: 로봇 대신 success_load2를 robot-events에 주입한다.
  confirmPlace,

  // 수령대 "수령하기" 버튼 전용: 눌렀을 때만 주문을 수령대에서 내린다.
  pickUpOrder,

  // 티칭 팬던트 전용 (PRD: assets/docs/prd-teaching-pendant.md 6장). 활성화/비활성화는
  // 같은 세션 엔드포인트의 enable:true/false 요청으로 나뉜다.
  enableTeachingPendant: () => setTeachingPendantSession(true),
  disableTeachingPendant: () => setTeachingPendantSession(false),

  sendJog: (body: JogRequestBody) =>
    teachingPendantRequest<{ jog_id: string }>("/api/teaching-pendant/jog", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  sendGripper: (action: GripperAction) =>
    teachingPendantRequest<{ gripper_cmd_id: string }>("/api/teaching-pendant/gripper", {
      method: "POST",
      body: JSON.stringify({ action }),
    }),

  stopTeachingPendant: () =>
    teachingPendantRequest<Record<string, unknown>>("/api/teaching-pendant/stop", { method: "POST" }),
};
