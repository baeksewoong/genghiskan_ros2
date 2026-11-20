/** Unit of joint angles received at module boundaries. Internal math always uses radians. */
export type AngleUnit = "rad" | "deg";

/** Canonical 6-DOF joint angle tuple [joint_1 .. joint_6]. */
export type JointTuple6 = [number, number, number, number, number, number];

export type JointInput =
  | readonly number[]
  | Record<string, number>;

export type ViewerStatus = "loading" | "ready" | "stale" | "error";

export type ConnectionStatus = "connected" | "stale" | "disconnected";

export type CameraPreset = "iso" | "front" | "top" | "side";

export type GripperType = "none" | "rg2";

export type GripperCommandAction = "open" | "close" | "set_width";

export interface GripperCommandEvent {
  action: GripperCommandAction;
  widthMm: number;
}

/** Doosan standard home targets: "ready" = [0, 0, 90, 0, 90, 0] deg, "zero" = [0, 0, 0, 0, 0, 0] deg. */
export type DoosanHomeTarget = "ready" | "zero";

export interface DoosanHomeEvent {
  target: DoosanHomeTarget;
  jointsRad: JointTuple6;
  jointsDeg: JointTuple6;
}

export interface JointLimitRange {
  lowerRad: number;
  upperRad: number;
}

export interface JointLimitWarning {
  jointName: string;
  valueRad: number;
  lowerRad: number;
  upperRad: number;
  utilization: number;
}

/** Standard FastAPI /ws/client payload contract for real-time M0609 joint updates. */
export interface RobotJointsEventPayload {
  robot_id: string;
  seq?: number;
  timestamp_ms: number;
  angle_unit: AngleUnit;
  joints: JointTuple6;
  gripper?: {
    type: "rg2";
    width_mm: number;
    is_gripping?: boolean;
  };
  source?: "virtual_robot" | "ros2_sfarm_bridge" | "mock";
}

export interface DoosanViewerOptions {
  /** Base URL containing URDF and meshes/ (e.g. "/assets/doosan/m0609_rg2"). */
  assetsBaseUrl: string;
  /** Optional custom URDF filename relative to assetsBaseUrl (defaults to "m0609_rg2.urdf" if gripper="rg2", else "m0609.urdf"). */
  urdfFileName?: string;
  /** End-effector gripper attachment mode (default: "none"). */
  gripper?: GripperType;
  /** Initial RG2 opening width in millimeters [0, 110] (default: 110). */
  initialGripperWidthMm?: number;
  /** Default input angle unit for updateJoints() (default: "rad"). */
  angleUnit?: AngleUnit;
  /** Background color hex string or "transparent" (default: "#0f172a"). */
  backgroundColor?: string;
  /** Show ground grid (default: true). */
  showGrid?: boolean;
  /** Show the loading-rack (적재대, left) and workbench+receiving-tray (작업대/수령대, right) schematic furniture (default: true). */
  showStations?: boolean;
  /** Show base & TCP RGB=XYZ coordinate axes (default: true). */
  showAxes?: boolean;
  /** Clamp incoming joint angles to URDF limits (default: true). */
  clampToLimits?: boolean;
  /** Interpolation lookback delay in ms to smooth network jitter (default: 50). */
  interpolationDelayMs?: number;
  /** Stale telemetry timeout in ms (default: 500). */
  staleTimeoutMs?: number;
  /** Initial camera preset (default: "iso"). */
  cameraPreset?: CameraPreset;
  onStatusChange?: (status: ViewerStatus) => void;
  onJointLimitWarning?: (warnings: JointLimitWarning[]) => void;
  onError?: (error: Error) => void;
}

export interface ViewerInstance {
  updateJoints(
    joints: JointInput,
    timestampMs?: number,
    angleUnitOverride?: AngleUnit
  ): boolean;
  setCameraPreset(preset: CameraPreset): void;
  setShowGrid(visible: boolean): void;
  setShowStations(visible: boolean): void;
  setShowAxes(visible: boolean): void;
  goHome(
    target?: DoosanHomeTarget,
    customJoints?: JointInput,
    angleUnitOverride?: AngleUnit
  ): JointTuple6 | null;
  updateGripper(widthMm: number, timestampMs?: number): boolean;
  setGripperOpen(open: boolean, timestampMs?: number): boolean;
  getCurrentGripperWidthMm(): number;
  getCurrentJointsRad(): JointTuple6;
  resize(): void;
  dispose(): void;
}
