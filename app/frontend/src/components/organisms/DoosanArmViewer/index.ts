import { DoosanM0609SceneViewer } from "./core/viewer";
import type { DoosanViewerOptions, ViewerInstance } from "./transports/types";

export function createDoosanM0609Viewer(
  container: HTMLElement,
  options: DoosanViewerOptions
): ViewerInstance {
  return new DoosanM0609SceneViewer(container, options);
}

export { DoosanM0609SceneViewer } from "./core/viewer";
export { M0609RobotRig } from "./core/robot_rig";
export { JointStateBuffer } from "./core/state_buffer";
export {
  DOOSAN_HOME_POSES_DEG,
  DOOSAN_HOME_POSES_RAD,
  M0609_JOINT_NAMES,
  RG2_MASTER_JOINT_NAME,
  RG2_MAX_WIDTH_MM,
  RG2_MIN_WIDTH_MM,
  clampJointValue,
  clampRg2WidthMm,
  degToRad,
  isFiniteTuple6,
  lerpJointTuple,
  normalizeJointInput,
  radToDeg,
  resolveHomePoseRad,
  rg2WidthMmToJointRad,
  tupleRadToDeg,
} from "./core/math";
export { MockTrajectoryAdapter, evaluateMockPoseRad } from "./transports/mock_adapter";
export type {
  AngleUnit,
  CameraPreset,
  ConnectionStatus,
  DoosanHomeEvent,
  DoosanHomeTarget,
  DoosanViewerOptions,
  GripperCommandAction,
  GripperCommandEvent,
  GripperType,
  JointInput,
  JointLimitRange,
  JointLimitWarning,
  JointTuple6,
  RobotJointsEventPayload,
  ViewerInstance,
  ViewerStatus,
} from "./transports/types";
