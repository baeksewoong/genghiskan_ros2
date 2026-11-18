import type { JointTuple6, RobotJointsEventPayload } from "./types";

export interface MockTrajectoryOptions {
  hz?: number;
  robotId?: string;
  onFrame: (payload: RobotJointsEventPayload) => void;
}

/**
 * Generates smooth, joint-limit-safe M0609 pick-and-place mock trajectories in radians
 * for standalone preview and integration tests.
 */
export class MockTrajectoryAdapter {
  private readonly intervalMs: number;
  private readonly robotId: string;
  private readonly onFrame: (payload: RobotJointsEventPayload) => void;
  private timerId: ReturnType<typeof setInterval> | null = null;
  private startMs = 0;
  private seq = 0;

  constructor(options: MockTrajectoryOptions) {
    const hz = Math.max(1, Math.min(120, options.hz ?? 30));
    this.intervalMs = Math.round(1000 / hz);
    this.robotId = options.robotId ?? "m0609_mock";
    this.onFrame = options.onFrame;
  }

  start(): void {
    if (this.timerId !== null) return;
    this.startMs = Date.now();
    this.seq = 0;
    this.timerId = setInterval(() => {
      const now = Date.now();
      const t = (now - this.startMs) / 1000;
      const joints = evaluateMockPoseRad(t);
      this.onFrame({
        robot_id: this.robotId,
        seq: ++this.seq,
        timestamp_ms: now,
        angle_unit: "rad",
        joints,
        source: "mock",
      });
    }, this.intervalMs);
  }

  stop(): void {
    if (this.timerId !== null) {
      clearInterval(this.timerId);
      this.timerId = null;
    }
  }
}

export function evaluateMockPoseRad(tSec: number): JointTuple6 {
  return [
    0.75 * Math.sin(0.6 * tSec),
    -0.35 + 0.25 * Math.sin(0.8 * tSec),
    1.35 + 0.35 * Math.cos(0.8 * tSec),
    0.45 * Math.sin(1.2 * tSec),
    0.95 + 0.35 * Math.sin(0.7 * tSec),
    1.1 * Math.sin(1.0 * tSec),
  ];
}
