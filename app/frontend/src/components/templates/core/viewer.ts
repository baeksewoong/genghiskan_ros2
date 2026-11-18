import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type {
  AngleUnit,
  CameraPreset,
  DoosanHomeTarget,
  DoosanViewerOptions,
  JointInput,
  JointTuple6,
  ViewerInstance,
  ViewerStatus,
} from "../transports/types";
import {
  RG2_MAX_WIDTH_MM,
  RG2_MIN_WIDTH_MM,
  clampRg2WidthMm,
  lerpJointTuple,
  resolveHomePoseRad,
} from "./math";
import { M0609RobotRig } from "./robot_rig";
import { JointStateBuffer } from "./state_buffer";

const CAMERA_PRESETS: Record<CameraPreset, { pos: [number, number, number]; target: [number, number, number] }> = {
  iso: { pos: [1.15, 0.95, 1.15], target: [0, 0.42, 0] },
  front: { pos: [1.45, 0.48, 0.0], target: [0, 0.42, 0] },
  side: { pos: [0.0, 0.48, 1.45], target: [0, 0.42, 0] },
  top: { pos: [0.01, 1.8, 0.01], target: [0, 0.35, 0] },
};

export class DoosanM0609SceneViewer implements ViewerInstance {
  private readonly container: HTMLElement;
  private readonly options: DoosanViewerOptions;
  private readonly scene: THREE.Scene;
  private readonly camera: THREE.PerspectiveCamera;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly controls: OrbitControls;
  private readonly grid: THREE.GridHelper;
  private readonly rig: M0609RobotRig;
  private readonly stateBuffer: JointStateBuffer;
  private readonly resizeObserver: ResizeObserver | null;

  private rafId: number | null = null;
  private disposed = false;
  private currentStatus: ViewerStatus = "loading";
  private lastWarningSignature = "";
  private homeTransition: {
    from: JointTuple6;
    to: JointTuple6;
    startMs: number;
    durationMs: number;
  } | null = null;
  private gripperCurrentMm: number;
  private gripperTargetMm: number;
  private gripperLastTickMs = Date.now();

  constructor(container: HTMLElement, options: DoosanViewerOptions) {
    this.container = container;
    this.options = options;

    this.scene = new THREE.Scene();
    const bg = options.backgroundColor ?? "#0f172a";
    this.scene.background = bg === "transparent" ? null : new THREE.Color(bg);

    const width = Math.max(1, container.clientWidth || 640);
    const height = Math.max(1, container.clientHeight || 480);

    this.camera = new THREE.PerspectiveCamera(45, width / height, 0.05, 50);
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: bg === "transparent",
      powerPreference: "high-performance",
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(width, height);
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.domElement.style.display = "block";
    this.renderer.domElement.style.width = "100%";
    this.renderer.domElement.style.height = "100%";
    container.appendChild(this.renderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.minDistance = 0.35;
    this.controls.maxDistance = 5.0;

    this.setupLights();

    this.grid = new THREE.GridHelper(2.4, 24, 0x334155, 0x1e293b);
    this.grid.visible = options.showGrid ?? true;
    this.scene.add(this.grid);

    this.rig = new M0609RobotRig({
      clampToLimits: options.clampToLimits ?? true,
    });
    const initWidth = clampRg2WidthMm(options.initialGripperWidthMm ?? RG2_MAX_WIDTH_MM);
    this.gripperCurrentMm = initWidth;
    this.gripperTargetMm = initWidth;
    this.rig.applyGripperWidthMm(initWidth);
    this.scene.add(this.rig.rootGroup);

    this.stateBuffer = new JointStateBuffer({
      interpolationDelayMs: options.interpolationDelayMs ?? 50,
      staleTimeoutMs: options.staleTimeoutMs ?? 500,
    });

    this.setCameraPreset(options.cameraPreset ?? "iso");

    if (typeof ResizeObserver !== "undefined") {
      this.resizeObserver = new ResizeObserver(() => this.resize());
      this.resizeObserver.observe(container);
    } else {
      this.resizeObserver = null;
    }

    this.renderer.domElement.addEventListener("webglcontextlost", this.handleContextLost);

    void this.initRobot();
    this.startLoop();
  }

  private setupLights(): void {
    const hemi = new THREE.HemisphereLight(0xf8fafc, 0x334155, 0.85);
    this.scene.add(hemi);

    const key = new THREE.DirectionalLight(0xffffff, 1.35);
    key.position.set(2.2, 3.4, 2.0);
    key.castShadow = true;
    key.shadow.mapSize.set(1024, 1024);
    key.shadow.camera.near = 0.5;
    key.shadow.camera.far = 10;
    const d = 1.4;
    key.shadow.camera.left = -d;
    key.shadow.camera.right = d;
    key.shadow.camera.top = d;
    key.shadow.camera.bottom = -d;
    this.scene.add(key);

    const fill = new THREE.DirectionalLight(0x93c5fd, 0.45);
    fill.position.set(-2.0, 1.5, -1.8);
    this.scene.add(fill);
  }

  private async initRobot(): Promise<void> {
    this.emitStatus("loading");
    try {
      const defaultUrdf = this.options.gripper === "rg2" ? "m0609_rg2.urdf" : "m0609.urdf";
      await this.rig.load({
        assetsBaseUrl: this.options.assetsBaseUrl,
        urdfFileName: this.options.urdfFileName ?? defaultUrdf,
        clampToLimits: this.options.clampToLimits,
        showAxes: this.options.showAxes,
      });
      if (!this.disposed) {
        this.emitStatus("ready");
      }
    } catch (err) {
      if (!this.disposed) {
        this.emitStatus("error");
        this.options.onError?.(err instanceof Error ? err : new Error(String(err)));
      }
    }
  }

  private handleContextLost = (event: Event): void => {
    event.preventDefault();
    this.emitStatus("error");
    this.options.onError?.(new Error("WebGL context lost"));
  };

  private emitStatus(next: ViewerStatus): void {
    if (this.currentStatus === next) return;
    this.currentStatus = next;
    this.options.onStatusChange?.(next);
  }

  updateJoints(
    joints: JointInput,
    timestampMs: number = Date.now(),
    angleUnitOverride?: AngleUnit
  ): boolean {
    if (this.disposed) return false;
    this.homeTransition = null;
    const unit = angleUnitOverride ?? this.options.angleUnit ?? "rad";
    const ok = this.stateBuffer.push(joints, unit, timestampMs, Date.now());
    if (!ok) {
      this.options.onError?.(
        new Error("Rejected joint frame (non-finite, incomplete, or out-of-order timestamp)")
      );
    }
    return ok;
  }

  setCameraPreset(preset: CameraPreset): void {
    const cfg = CAMERA_PRESETS[preset];
    this.camera.position.set(...cfg.pos);
    this.controls.target.set(...cfg.target);
    this.controls.update();
  }

  setShowGrid(visible: boolean): void {
    this.grid.visible = visible;
  }

  setShowAxes(visible: boolean): void {
    this.rig.setShowAxes(visible);
  }

  goHome(
    target: DoosanHomeTarget = "ready",
    customJoints?: JointInput,
    angleUnitOverride?: AngleUnit
  ): JointTuple6 | null {
    if (this.disposed) return null;
    const poseRad = resolveHomePoseRad(
      target,
      customJoints,
      angleUnitOverride ?? this.options.angleUnit ?? "rad"
    );
    if (!poseRad) {
      this.options.onError?.(new Error("Invalid custom home joint configuration"));
      return null;
    }
    const now = Date.now();
    this.homeTransition = {
      from: this.rig.getCurrentJointsRad(),
      to: poseRad,
      startMs: now,
      durationMs: 600,
    };
    this.stateBuffer.resetTo(poseRad, now);
    return poseRad;
  }

  getCurrentJointsRad(): JointTuple6 {
    return this.rig.getCurrentJointsRad();
  }

  updateGripper(widthMm: number, _timestampMs: number = Date.now()): boolean {
    if (this.disposed || !Number.isFinite(widthMm)) {
      if (!Number.isFinite(widthMm)) {
        this.options.onError?.(new Error(`Rejected non-finite gripper width: ${widthMm}`));
      }
      return false;
    }
    this.gripperTargetMm = clampRg2WidthMm(widthMm);
    return true;
  }

  setGripperOpen(open: boolean, timestampMs: number = Date.now()): boolean {
    return this.updateGripper(open ? RG2_MAX_WIDTH_MM : RG2_MIN_WIDTH_MM, timestampMs);
  }

  getCurrentGripperWidthMm(): number {
    return this.gripperCurrentMm;
  }

  resize(): void {
    if (this.disposed) return;
    const width = Math.max(1, this.container.clientWidth || 1);
    const height = Math.max(1, this.container.clientHeight || 1);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }

  private startLoop(): void {
    const tick = () => {
      if (this.disposed) return;
      this.rafId = window.requestAnimationFrame(tick);

      const now = Date.now();
      const dtSec = Math.min(0.1, Math.max(0, (now - this.gripperLastTickMs) / 1000));
      this.gripperLastTickMs = now;
      if (Math.abs(this.gripperTargetMm - this.gripperCurrentMm) > 0.05) {
        // Smooth RG2 actuation (~260 mm/s max visual speed)
        const maxStep = 260 * Math.max(dtSec, 1 / 60);
        const delta = this.gripperTargetMm - this.gripperCurrentMm;
        const step = Math.sign(delta) * Math.min(Math.abs(delta), maxStep);
        this.gripperCurrentMm += step;
        this.rig.applyGripperWidthMm(this.gripperCurrentMm);
      } else if (this.gripperCurrentMm !== this.gripperTargetMm) {
        this.gripperCurrentMm = this.gripperTargetMm;
        this.rig.applyGripperWidthMm(this.gripperCurrentMm);
      }

      if (this.homeTransition) {
        const elapsed = now - this.homeTransition.startMs;
        const rawT = Math.min(1, Math.max(0, elapsed / this.homeTransition.durationMs));
        // Smooth cosine ease-in-out
        const eased = 0.5 - 0.5 * Math.cos(Math.PI * rawT);
        const interp = lerpJointTuple(this.homeTransition.from, this.homeTransition.to, eased);
        this.rig.applyJointsRad(interp);
        if (rawT >= 1) {
          this.stateBuffer.resetTo(this.homeTransition.to, now);
          this.homeTransition = null;
        }
      } else {
        const sampled = this.stateBuffer.sample(now);
        if (sampled.hasData) {
          const warnings = this.rig.applyJointsRad(sampled.jointsRad);
          const sig = warnings.map((w) => `${w.jointName}:${w.utilization.toFixed(2)}`).join(",");
          if (sig !== this.lastWarningSignature) {
            this.lastWarningSignature = sig;
            this.options.onJointLimitWarning?.(warnings);
          }
          if (this.currentStatus === "ready" || this.currentStatus === "stale") {
            this.emitStatus(sampled.isStale ? "stale" : "ready");
          }
        }
      }

      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    };
    this.rafId = window.requestAnimationFrame(tick);
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;

    if (this.rafId !== null) {
      window.cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }

    this.resizeObserver?.disconnect();
    this.renderer.domElement.removeEventListener("webglcontextlost", this.handleContextLost);
    this.controls.dispose();
    this.rig.dispose();
    this.grid.geometry.dispose();
    (this.grid.material as THREE.Material).dispose();
    this.stateBuffer.clear();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
