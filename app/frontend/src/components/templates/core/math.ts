import type {
  AngleUnit,
  DoosanHomeTarget,
  JointInput,
  JointLimitRange,
  JointTuple6,
} from "../transports/types";

export const M0609_JOINT_NAMES = [
  "joint_1",
  "joint_2",
  "joint_3",
  "joint_4",
  "joint_5",
  "joint_6",
] as const;

/** Standard Doosan M0609 home/ready joint configurations in degrees (DSR_ROBOT2 posj). */
export const DOOSAN_HOME_POSES_DEG: Record<DoosanHomeTarget, JointTuple6> = {
  ready: [0, 0, 90, 0, 90, 0],
  zero: [0, 0, 0, 0, 0, 0],
};

/** Standard Doosan M0609 home/ready joint configurations in radians. */
export const DOOSAN_HOME_POSES_RAD: Record<DoosanHomeTarget, JointTuple6> = {
  ready: [0, 0, Math.PI / 2, 0, Math.PI / 2, 0],
  zero: [0, 0, 0, 0, 0, 0],
};

const JOINT_ALIAS_GROUPS: ReadonlyArray<readonly string[]> = [
  ["joint_1", "j1", "joint1"],
  ["joint_2", "j2", "joint2"],
  ["joint_3", "j3", "joint3"],
  ["joint_4", "j4", "joint4"],
  ["joint_5", "j5", "joint5"],
  ["joint_6", "j6", "joint6"],
];

const DEG_TO_RAD = Math.PI / 180;
const RAD_TO_DEG = 180 / Math.PI;

export function degToRad(deg: number): number {
  return deg * DEG_TO_RAD;
}

export function radToDeg(rad: number): number {
  return rad * RAD_TO_DEG;
}

export function isFiniteTuple6(values: readonly number[]): values is JointTuple6 {
  if (values.length !== 6) return false;
  for (let i = 0; i < 6; i++) {
    if (!Number.isFinite(values[i])) return false;
  }
  return true;
}

/**
 * Normalize array or named map joint input into a finite 6-element radian tuple.
 * Returns null if any required joint is missing or non-finite (NaN/Infinity).
 */
export function normalizeJointInput(
  input: JointInput,
  unit: AngleUnit
): JointTuple6 | null {
  const raw: number[] = new Array(6);

  if (Array.isArray(input)) {
    if (input.length < 6) return null;
    for (let i = 0; i < 6; i++) {
      raw[i] = Number(input[i]);
    }
  } else {
    const map = input as Record<string, number>;
    for (let i = 0; i < 6; i++) {
      const aliases = JOINT_ALIAS_GROUPS[i];
      let found: number | undefined;
      for (const alias of aliases) {
        if (Object.prototype.hasOwnProperty.call(map, alias)) {
          found = map[alias];
          break;
        }
      }
      if (found === undefined) return null;
      raw[i] = Number(found);
    }
  }

  for (let i = 0; i < 6; i++) {
    if (!Number.isFinite(raw[i])) return null;
    if (unit === "deg") {
      raw[i] = degToRad(raw[i]);
    }
  }

  return raw as JointTuple6;
}

export function clampJointValue(valueRad: number, limit: JointLimitRange): number {
  if (!Number.isFinite(valueRad)) {
    throw new RangeError(`Non-finite joint value: ${valueRad}`);
  }
  return Math.max(limit.lowerRad, Math.min(limit.upperRad, valueRad));
}

export function lerpJointTuple(a: JointTuple6, b: JointTuple6, alpha: number): JointTuple6 {
  const t = Math.max(0, Math.min(1, alpha));
  return [
    a[0] + (b[0] - a[0]) * t,
    a[1] + (b[1] - a[1]) * t,
    a[2] + (b[2] - a[2]) * t,
    a[3] + (b[3] - a[3]) * t,
    a[4] + (b[4] - a[4]) * t,
    a[5] + (b[5] - a[5]) * t,
  ];
}

/**
 * Resolve a Doosan home pose in radians (either preset target or custom override).
 */
export function resolveHomePoseRad(
  target: DoosanHomeTarget = "ready",
  customJoints?: JointInput,
  unit: AngleUnit = "rad"
): JointTuple6 | null {
  if (customJoints !== undefined) {
    return normalizeJointInput(customJoints, unit);
  }
  return [...DOOSAN_HOME_POSES_RAD[target]];
}

export function tupleRadToDeg(jointsRad: JointTuple6): JointTuple6 {
  return [
    radToDeg(jointsRad[0]),
    radToDeg(jointsRad[1]),
    radToDeg(jointsRad[2]),
    radToDeg(jointsRad[3]),
    radToDeg(jointsRad[4]),
    radToDeg(jointsRad[5]),
  ];
}

export const RG2_MASTER_JOINT_NAME = "rg2_gripper_joint";
export const RG2_MIN_WIDTH_MM = 0;
export const RG2_MAX_WIDTH_MM = 110;

// Exact 4-bar linkage geometry constants from onrobot_description rg2_v1
const RG2_LINK_R = Math.hypot(0.04868, 0.0256);
const RG2_PHI = Math.atan2(0.0256, 0.04868);
const RG2_OFFSET = -0.772;
const RG2_C0 = 0.002002;
const RG2_MAX_URDF_GAP_MM =
  -2000 * (RG2_C0 + RG2_LINK_R * Math.sin(RG2_OFFSET - RG2_PHI));

export function clampRg2WidthMm(widthMm: number): number {
  if (!Number.isFinite(widthMm)) {
    throw new RangeError(`Non-finite RG2 width: ${widthMm}`);
  }
  return Math.max(RG2_MIN_WIDTH_MM, Math.min(RG2_MAX_WIDTH_MM, widthMm));
}

/**
 * Convert OnRobot RG2 finger gap width in millimeters [0, 110] to the master
 * URDF joint angle in radians (0.0 rad = open, ~1.22 rad = closed).
 */
export function rg2WidthMmToJointRad(
  widthMm: number,
  limit: JointLimitRange = { lowerRad: 0.0, upperRad: 1.22 }
): number {
  const clampedMm = clampRg2WidthMm(widthMm);
  const targetGapMm = (clampedMm / RG2_MAX_WIDTH_MM) * RG2_MAX_URDF_GAP_MM;
  const targetXInner = -targetGapMm / 2000;
  const sinVal = Math.max(-1, Math.min(1, (targetXInner - RG2_C0) / RG2_LINK_R));
  const theta = RG2_PHI + Math.asin(sinVal);
  const q = theta - RG2_OFFSET;
  return clampJointValue(q, limit);
}
