import { createDoosanM0609Viewer } from "./index";
import type {
  AngleUnit,
  CameraPreset,
  DoosanHomeTarget,
  GripperType,
  JointInput,
  JointTuple6,
  ViewerInstance,
} from "./transports/types";

/**
 * Framework-agnostic Web Component (<doosan-arm-viewer>) with Shadow DOM isolation.
 */
export class DoosanArmViewerElement extends HTMLElement {
  static get observedAttributes(): string[] {
    return ["assets-base-url", "gripper", "angle-unit", "show-grid", "show-axes", "camera-preset"];
  }

  private viewer: ViewerInstance | null = null;
  private mountEl: HTMLDivElement | null = null;

  connectedCallback(): void {
    if (!this.shadowRoot) {
      const shadow = this.attachShadow({ mode: "open" });
      const style = document.createElement("style");
      style.textContent = ":host { display: block; width: 100%; height: 100%; min-height: 280px; }";
      this.mountEl = document.createElement("div");
      this.mountEl.style.width = "100%";
      this.mountEl.style.height = "100%";
      shadow.append(style, this.mountEl);
    }
    this.initViewer();
  }

  disconnectedCallback(): void {
    this.viewer?.dispose();
    this.viewer = null;
  }

  attributeChangedCallback(name: string, oldVal: string | null, newVal: string | null): void {
    if (oldVal === newVal) return;
    if (name === "assets-base-url" || name === "gripper") {
      this.initViewer();
      return;
    }
    if (!this.viewer) return;
    if (name === "show-grid") {
      this.viewer.setShowGrid(newVal !== "false");
    } else if (name === "show-axes") {
      this.viewer.setShowAxes(newVal !== "false");
    } else if (name === "camera-preset" && newVal) {
      this.viewer.setCameraPreset(newVal as CameraPreset);
    }
  }

  updateJoints(
    joints: JointInput,
    timestampMs?: number,
    angleUnitOverride?: AngleUnit
  ): boolean {
    return this.viewer?.updateJoints(joints, timestampMs, angleUnitOverride) ?? false;
  }

  goHome(
    target: DoosanHomeTarget = "ready",
    customJoints?: JointInput,
    angleUnitOverride?: AngleUnit
  ): JointTuple6 | null {
    return this.viewer?.goHome(target, customJoints, angleUnitOverride) ?? null;
  }

  updateGripper(widthMm: number, timestampMs?: number): boolean {
    return this.viewer?.updateGripper(widthMm, timestampMs) ?? false;
  }

  setGripperOpen(open: boolean, timestampMs?: number): boolean {
    return this.viewer?.setGripperOpen(open, timestampMs) ?? false;
  }

  private initViewer(): void {
    if (!this.isConnected || !this.mountEl) return;
    const assetsBaseUrl = this.getAttribute("assets-base-url");
    if (!assetsBaseUrl) return;

    this.viewer?.dispose();
    this.viewer = createDoosanM0609Viewer(this.mountEl, {
      assetsBaseUrl,
      gripper: (this.getAttribute("gripper") as GripperType) || "none",
      angleUnit: (this.getAttribute("angle-unit") as AngleUnit) || "rad",
      showGrid: this.getAttribute("show-grid") !== "false",
      showAxes: this.getAttribute("show-axes") !== "false",
      cameraPreset: (this.getAttribute("camera-preset") as CameraPreset) || "iso",
      onStatusChange: (status) => {
        this.dispatchEvent(new CustomEvent("statuschange", { detail: { status } }));
      },
      onError: (error) => {
        this.dispatchEvent(new CustomEvent("viewererror", { detail: { error } }));
      },
    });
  }
}

export function registerDoosanArmViewerElement(tagName = "doosan-arm-viewer"): void {
  if (typeof customElements !== "undefined" && !customElements.get(tagName)) {
    customElements.define(tagName, DoosanArmViewerElement);
  }
}
