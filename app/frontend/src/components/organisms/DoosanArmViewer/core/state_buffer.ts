import type { AngleUnit, JointInput, JointTuple6 } from "../transports/types";
import { lerpJointTuple, normalizeJointInput } from "./math";

interface TimedJointFrame {
  sourceTimestampMs: number;
  receivedAtMs: number;
  jointsRad: JointTuple6;
}

export interface JointStateBufferOptions {
  interpolationDelayMs?: number;
  staleTimeoutMs?: number;
}

export interface SampledJointState {
  jointsRad: JointTuple6;
  isStale: boolean;
  hasData: boolean;
  lastTimestampMs: number | null;
}

const ZERO_JOINTS: JointTuple6 = [0, 0, 0, 0, 0, 0];

/**
 * Buffers incoming 6-DOF joint frames, rejects non-finite or out-of-order packets,
 * linearly interpolates across a short lookback delay, and tracks stale timeouts.
 */
export class JointStateBuffer {
  private readonly interpolationDelayMs: number;
  private readonly staleTimeoutMs: number;
  private readonly frames: TimedJointFrame[] = [];
  private lastAcceptedSourceTs: number | null = null;
  private lastReceivedLocalMs: number | null = null;

  constructor(options: JointStateBufferOptions = {}) {
    this.interpolationDelayMs = Math.max(0, options.interpolationDelayMs ?? 50);
    this.staleTimeoutMs = Math.max(50, options.staleTimeoutMs ?? 500);
  }

  /**
   * Push a joint measurement. Returns false if rejected (invalid/NaN or out-of-order).
   */
  push(
    input: JointInput,
    unit: AngleUnit,
    sourceTimestampMs: number,
    nowMs: number = Date.now()
  ): boolean {
    if (!Number.isFinite(sourceTimestampMs) || !Number.isFinite(nowMs)) {
      return false;
    }

    const jointsRad = normalizeJointInput(input, unit);
    if (!jointsRad) {
      return false;
    }

    // Reject stale / out-of-order packets (e.g., delayed or duplicated messages)
    if (
      this.lastAcceptedSourceTs !== null &&
      sourceTimestampMs < this.lastAcceptedSourceTs
    ) {
      return false;
    }

    const frame: TimedJointFrame = {
      sourceTimestampMs,
      receivedAtMs: nowMs,
      jointsRad,
    };

    if (
      this.frames.length > 0 &&
      this.frames[this.frames.length - 1].sourceTimestampMs === sourceTimestampMs
    ) {
      this.frames[this.frames.length - 1] = frame;
    } else {
      this.frames.push(frame);
      // Keep only recent history needed for interpolation
      while (this.frames.length > 16) {
        this.frames.shift();
      }
    }

    this.lastAcceptedSourceTs = sourceTimestampMs;
    this.lastReceivedLocalMs = nowMs;
    return true;
  }

  sample(nowMs: number = Date.now()): SampledJointState {
    if (this.frames.length === 0 || this.lastReceivedLocalMs === null) {
      return {
        jointsRad: [...ZERO_JOINTS],
        isStale: false,
        hasData: false,
        lastTimestampMs: null,
      };
    }

    const isStale = nowMs - this.lastReceivedLocalMs > this.staleTimeoutMs;
    const latest = this.frames[this.frames.length - 1];

    if (this.frames.length === 1 || this.interpolationDelayMs <= 0) {
      return {
        jointsRad: [...latest.jointsRad],
        isStale,
        hasData: true,
        lastTimestampMs: latest.sourceTimestampMs,
      };
    }

    const renderLocalMs = nowMs - this.interpolationDelayMs;
    const first = this.frames[0];
    if (renderLocalMs <= first.receivedAtMs) {
      return {
        jointsRad: [...first.jointsRad],
        isStale,
        hasData: true,
        lastTimestampMs: latest.sourceTimestampMs,
      };
    }

    if (renderLocalMs >= latest.receivedAtMs) {
      return {
        jointsRad: [...latest.jointsRad],
        isStale,
        hasData: true,
        lastTimestampMs: latest.sourceTimestampMs,
      };
    }

    for (let i = 0; i < this.frames.length - 1; i++) {
      const a = this.frames[i];
      const b = this.frames[i + 1];
      if (renderLocalMs >= a.receivedAtMs && renderLocalMs <= b.receivedAtMs) {
        const span = b.receivedAtMs - a.receivedAtMs;
        const alpha = span > 0 ? (renderLocalMs - a.receivedAtMs) / span : 1;
        return {
          jointsRad: lerpJointTuple(a.jointsRad, b.jointsRad, alpha),
          isStale,
          hasData: true,
          lastTimestampMs: latest.sourceTimestampMs,
        };
      }
    }

    return {
      jointsRad: [...latest.jointsRad],
      isStale,
      hasData: true,
      lastTimestampMs: latest.sourceTimestampMs,
    };
  }

  clear(): void {
    this.frames.length = 0;
    this.lastAcceptedSourceTs = null;
    this.lastReceivedLocalMs = null;
  }

  /** Force-reset buffer to a specific pose (used by local goHome() regardless of clock skew). */
  resetTo(jointsRad: JointTuple6, nowMs: number = Date.now()): void {
    this.frames.length = 0;
    const copy: JointTuple6 = [...jointsRad];
    this.frames.push({
      sourceTimestampMs: nowMs,
      receivedAtMs: nowMs,
      jointsRad: copy,
    });
    this.lastAcceptedSourceTs = nowMs;
    this.lastReceivedLocalMs = nowMs;
  }
}
