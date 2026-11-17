export type Shape = "TRIANGLE" | "SQUARE" | "STAR" | "CIRCLE";

export type OrderStatus =
  | "WAITING"
  // 작업요청(SQS) 경로 전용: LOAD 발행 성공 ~ pick_complete 수신 전까지 ("투입중").
  | "DISPATCHING"
  | "LOADING"
  | "PRINTING"
  | "PRINT_DONE"
  | "UNLOADING"
  | "READY_FOR_PICKUP"
  | "PICKED_UP";

export type PrinterStatus = "EMPTY" | "RESERVED" | "PRINTING" | "DONE" | "UNLOADING";
export type RobotState = "IDLE" | "BUSY" | "ERROR" | "DISCONNECTED";

// 작업요청(SQS) 경로 전용: 적재대 층(1~3)별 상태.
export type BoardStockSlotStatus = "EMPTY" | "RESERVED" | "OCCUPIED";

export interface BoardStockSlot {
  slot: number;
  status: BoardStockSlotStatus;
  updated_at: string;
}

export interface Order {
  id: number;
  user_id: number;
  customer_name: string | null;
  shape: Shape;
  print_duration_sec: number;
  status: OrderStatus;
  source: "AUTO" | "MANUAL";
  printer_slot: number | null;
  created_at: string;
  started_at: string | null;
  print_completed_at: string | null;
  ready_at: string | null;
  pickup_delay_sec: number | null;
  picked_up_at: string | null;
  updated_at: string;
}

export interface Printer {
  slot: number;
  status: PrinterStatus;
  current_order_id: number | null;
  customer_name: string | null;
  timer_ends_at: string | null;
  updated_at: string;
}

export interface RobotStatus {
  state: RobotState;
  current_task_id: number | null;
  bridge_connected: boolean;
}

export interface SimulatorSettings {
  time_scale: number;
}

export interface StateSnapshot {
  printers: Printer[];
  robot: RobotStatus;
  waiting_orders: Order[];
  active_orders: Order[];
  pickup_orders: Order[];
  simulator: SimulatorSettings;
}

export interface Envelope<T = unknown> {
  type: string;
  event_id: string;
  ts: string;
  data: T;
}

// 티칭 팬던트(실물 로봇 조그 제어) 전용 (PRD: assets/docs/prd-teaching-pendant.md).
// space=TASK면 Cartesian(X/Y/Z/Rx/Ry/Rz, ref_frame 필요), space=JOINT면 J1~J6(ref_frame 없음).
export type JogSpace = "TASK" | "JOINT";
export type JogRefFrame = "BASE" | "TOOL";
export type CartesianAxis = "X" | "Y" | "Z" | "RX" | "RY" | "RZ";
export type JointAxis = "J1" | "J2" | "J3" | "J4" | "J5" | "J6";
export type JogAxis = CartesianAxis | JointAxis;
export type JogDirection = 1 | -1;
export type GripperAction = "OPEN" | "CLOSE";

// 세션 활성화 응답(200)·jog_completed 이벤트의 current_pose에 쓰인다.
export interface TeachingPendantPose {
  space: JogSpace;
  posx?: number[];
  posj?: number[];
}

// SQS 모니터링 페이지 전용.
export interface SqsQueueStatus {
  name: string;
  configured: boolean;
  queue_url: string | null;
  visible?: number;
  in_flight?: number;
  delayed?: number;
  error?: string;
}

export interface SqsStatus {
  command_queue: SqsQueueStatus;
  event_queue: SqsQueueStatus;
}
