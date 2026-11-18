import type { CSSProperties } from "react";
import { useEffect, useImperativeHandle, useRef, useState, forwardRef } from "react";
import {
  RG2_MAX_WIDTH_MM,
  RG2_MIN_WIDTH_MM,
  createDoosanM0609Viewer,
  resolveHomePoseRad,
  tupleRadToDeg,
} from "./index";
import type {
  AngleUnit,
  CameraPreset,
  ConnectionStatus,
  DoosanHomeEvent,
  DoosanHomeTarget,
  GripperCommandEvent,
  GripperType,
  JointInput,
  JointLimitWarning,
  ViewerInstance,
  ViewerStatus,
} from "./transports/types";

export interface DoosanM0609ViewerProps {
  /** Base URL containing URDF and meshes/ (e.g. "/assets/doosan/m0609_rg2"). */
  assetsBaseUrl: string;
  urdfFileName?: string;
  /** Attached gripper type ("none" | "rg2", default: "none"). */
  gripper?: GripperType;
  /** Target RG2 finger opening width in mm [0, 110]. */
  gripperWidthMm?: number;
  /** Show Open / Close RG2 buttons overlay when gripper="rg2" (default: true). */
  showGripperControls?: boolean;
  /** Latest 6-DOF joint angles pushed by host (e.g. from useLiveState). */
  joints?: JointInput;
  /** Unit of incoming joints (default: "rad"). */
  angleUnit?: AngleUnit;
  /** Source timestamp in ms for interpolation and out-of-order protection. */
  timestampMs?: number;
  /** Optional host WebSocket connection status for badge display. */
  connectionStatus?: ConnectionStatus;
  backgroundColor?: string;
  showGrid?: boolean;
  showAxes?: boolean;
  showStatusBadge?: boolean;
  /** Show built-in "Home" button overlay (default: true). */
  showHomeButton?: boolean;
  /** Doosan home target ("ready" = [0,0,90,0,90,0] deg, "zero" = [0,0,0,0,0,0] deg). */
  homeTarget?: DoosanHomeTarget;
  /** Optional custom home joint override. */
  customHomeJoints?: JointInput;
  /** Unit for customHomeJoints (default: angleUnit). */
  homeAngleUnit?: AngleUnit;
  homeButtonLabel?: string;
  clampToLimits?: boolean;
  interpolationDelayMs?: number;
  staleTimeoutMs?: number;
  cameraPreset?: CameraPreset;
  className?: string;
  style?: CSSProperties;
  onStatusChange?: (status: ViewerStatus) => void;
  onJointLimitWarning?: (warnings: JointLimitWarning[]) => void;
  /**
   * Optional host callback to command the real Doosan robot (e.g. FastAPI -> SQS -> DSR_ROBOT2 movej).
   * If omitted, clicking Home moves the local 3D model directly via viewer.goHome().
   */
  onHomeClick?: (event: DoosanHomeEvent) => void | Promise<void>;
  /**
   * Optional host callback to command the real OnRobot RG2 gripper (e.g. FastAPI -> SQS -> ROS 2).
   * If omitted, clicking Open/Close animates the local 3D RG2 model directly.
   */
  onGripperCommand?: (event: GripperCommandEvent) => void | Promise<void>;
  onError?: (error: Error) => void;
}

const BADGE_COLORS: Record<string, string> = {
  ready: "#10b981",
  connected: "#10b981",
  loading: "#38bdf8",
  stale: "#f59e0b",
  disconnected: "#94a3b8",
  error: "#ef4444",
};

/**
 * React 18+ Wrapper for Doosan M0609 3D viewer.
 * Safe under React StrictMode double-mount and SSR-guarded (WebGL mounts in useEffect).
 */
export const DoosanM0609Viewer = forwardRef<ViewerInstance | null, DoosanM0609ViewerProps>(
  function DoosanM0609Viewer(
    {
      assetsBaseUrl,
      urdfFileName,
      gripper = "none",
      gripperWidthMm,
      showGripperControls = true,
      joints,
      angleUnit = "rad",
      timestampMs,
      connectionStatus,
      backgroundColor = "#0f172a",
      showGrid = true,
      showAxes = true,
      showStatusBadge = true,
      showHomeButton = true,
      homeTarget = "ready",
      customHomeJoints,
      homeAngleUnit,
      homeButtonLabel = "Home",
      clampToLimits = true,
      interpolationDelayMs = 50,
      staleTimeoutMs = 500,
      cameraPreset = "iso",
      className,
      style,
      onStatusChange,
      onJointLimitWarning,
      onHomeClick,
      onGripperCommand,
      onError,
    },
    ref
  ) {
    const containerRef = useRef<HTMLDivElement | null>(null);
    const viewerRef = useRef<ViewerInstance | null>(null);
    const [status, setStatus] = useState<ViewerStatus>("loading");
    const [limitCount, setLimitCount] = useState(0);
    const [homingBusy, setHomingBusy] = useState(false);
    const [gripperBusy, setGripperBusy] = useState(false);

    const callbacksRef = useRef({
      onStatusChange,
      onJointLimitWarning,
      onHomeClick,
      onGripperCommand,
      onError,
    });
    callbacksRef.current = {
      onStatusChange,
      onJointLimitWarning,
      onHomeClick,
      onGripperCommand,
      onError,
    };

    useImperativeHandle(ref, () => viewerRef.current as ViewerInstance, []);

    useEffect(() => {
      const container = containerRef.current;
      if (!container) return;

      const instance = createDoosanM0609Viewer(container, {
        assetsBaseUrl,
        urdfFileName,
        gripper,
        initialGripperWidthMm: gripperWidthMm,
        angleUnit,
        backgroundColor,
        showGrid,
        showAxes,
        clampToLimits,
        interpolationDelayMs,
        staleTimeoutMs,
        cameraPreset,
        onStatusChange: (next) => {
          setStatus(next);
          callbacksRef.current.onStatusChange?.(next);
        },
        onJointLimitWarning: (warnings) => {
          setLimitCount(warnings.length);
          callbacksRef.current.onJointLimitWarning?.(warnings);
        },
        onError: (err) => {
          callbacksRef.current.onError?.(err);
        },
      });

      viewerRef.current = instance;
      return () => {
        instance.dispose();
        if (viewerRef.current === instance) {
          viewerRef.current = null;
        }
      };
    }, [
      assetsBaseUrl,
      urdfFileName,
      gripper,
      backgroundColor,
      clampToLimits,
      interpolationDelayMs,
      staleTimeoutMs,
    ]);

    useEffect(() => {
      if (!joints || !viewerRef.current) return;
      viewerRef.current.updateJoints(joints, timestampMs ?? Date.now(), angleUnit);
    }, [joints, timestampMs, angleUnit]);

    useEffect(() => {
      if (gripperWidthMm === undefined || !viewerRef.current) return;
      viewerRef.current.updateGripper(gripperWidthMm, timestampMs ?? Date.now());
    }, [gripperWidthMm, timestampMs]);

    useEffect(() => {
      viewerRef.current?.setShowGrid(showGrid);
    }, [showGrid]);

    useEffect(() => {
      viewerRef.current?.setShowAxes(showAxes);
    }, [showAxes]);

    useEffect(() => {
      viewerRef.current?.setCameraPreset(cameraPreset);
    }, [cameraPreset]);

    const badgeLabel =
      status === "error"
        ? "ERROR"
        : status === "loading"
          ? "LOADING M0609..."
          : connectionStatus === "disconnected"
            ? "DISCONNECTED"
            : status === "stale" || connectionStatus === "stale"
              ? "STALE"
              : "LIVE";

    const badgeColor =
      BADGE_COLORS[
        status === "error" || status === "loading"
          ? status
          : connectionStatus ?? status
      ] ?? "#94a3b8";

    const handleHomeClick = async () => {
      if (homingBusy) return;
      const effectiveUnit = homeAngleUnit ?? angleUnit;
      const jointsRad = resolveHomePoseRad(homeTarget, customHomeJoints, effectiveUnit);
      if (!jointsRad) {
        callbacksRef.current.onError?.(new Error("Invalid custom home joint configuration"));
        return;
      }
      const jointsDeg = tupleRadToDeg(jointsRad);
      const handler = callbacksRef.current.onHomeClick;

      if (!handler) {
        viewerRef.current?.goHome(homeTarget, customHomeJoints, effectiveUnit);
        return;
      }

      try {
        setHomingBusy(true);
        await handler({ target: homeTarget, jointsRad, jointsDeg });
      } catch (err) {
        callbacksRef.current.onError?.(err instanceof Error ? err : new Error(String(err)));
      } finally {
        setHomingBusy(false);
      }
    };

    const handleGripperAction = async (open: boolean) => {
      if (gripperBusy) return;
      const widthMm = open ? RG2_MAX_WIDTH_MM : RG2_MIN_WIDTH_MM;
      const action = open ? "open" : "close";
      const handler = callbacksRef.current.onGripperCommand;

      if (!handler) {
        viewerRef.current?.setGripperOpen(open);
        return;
      }

      try {
        setGripperBusy(true);
        await handler({ action, widthMm });
      } catch (err) {
        callbacksRef.current.onError?.(err instanceof Error ? err : new Error(String(err)));
      } finally {
        setGripperBusy(false);
      }
    };

    return (
      <div
        className={className}
        style={{
          position: "relative",
          width: "100%",
          height: "100%",
          minHeight: 280,
          overflow: "hidden",
          ...style,
        }}
      >
        <div ref={containerRef} style={{ width: "100%", height: "100%" }} />
        {showStatusBadge && (
          <div
            style={{
              position: "absolute",
              top: 10,
              left: 10,
              zIndex: 10,
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "4px 10px",
              borderRadius: 999,
              background: "rgba(15, 23, 42, 0.78)",
              border: "1px solid rgba(148, 163, 184, 0.25)",
              color: "#f8fafc",
              fontSize: 11,
              fontWeight: 600,
              letterSpacing: "0.04em",
              pointerEvents: "none",
            }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                backgroundColor: badgeColor,
              }}
            />
            <span>{badgeLabel}</span>
            {limitCount > 0 && (
              <span style={{ color: "#fbbf24", marginLeft: 4 }}>
                LIMIT ({limitCount})
              </span>
            )}
          </div>
        )}
        <div
          style={{
            position: "absolute",
            top: 10,
            right: 10,
            zIndex: 10,
            display: "flex",
            gap: 6,
          }}
        >
          {gripper === "rg2" && showGripperControls && (
            <>
              <button
                type="button"
                data-testid="rg2-open-button"
                disabled={gripperBusy}
                onClick={() => void handleGripperAction(true)}
                title="Open OnRobot RG2 gripper (110 mm)"
                style={{
                  padding: "6px 10px",
                  borderRadius: 8,
                  background: "rgba(15, 23, 42, 0.85)",
                  border: "1px solid rgba(56, 189, 248, 0.45)",
                  color: "#e0f2fe",
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: gripperBusy ? "wait" : "pointer",
                }}
              >
                RG2 Open
              </button>
              <button
                type="button"
                data-testid="rg2-close-button"
                disabled={gripperBusy}
                onClick={() => void handleGripperAction(false)}
                title="Close OnRobot RG2 gripper (0 mm)"
                style={{
                  padding: "6px 10px",
                  borderRadius: 8,
                  background: "rgba(15, 23, 42, 0.85)",
                  border: "1px solid rgba(251, 191, 36, 0.45)",
                  color: "#fef3c7",
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: gripperBusy ? "wait" : "pointer",
                }}
              >
                RG2 Close
              </button>
            </>
          )}
          {showHomeButton && (
            <button
              type="button"
              data-testid="doosan-home-button"
              disabled={homingBusy}
              onClick={() => void handleHomeClick()}
              title={`Move M0609 to Doosan ${homeTarget} home position`}
              style={{
                padding: "6px 12px",
                borderRadius: 8,
                background: homingBusy ? "rgba(51, 65, 85, 0.85)" : "rgba(15, 23, 42, 0.85)",
                border: "1px solid rgba(148, 163, 184, 0.35)",
                color: "#f8fafc",
                fontSize: 12,
                fontWeight: 600,
                cursor: homingBusy ? "wait" : "pointer",
              }}
            >
              {homingBusy ? "Homing..." : homeButtonLabel}
            </button>
          )}
        </div>
      </div>
    );
  }
);
