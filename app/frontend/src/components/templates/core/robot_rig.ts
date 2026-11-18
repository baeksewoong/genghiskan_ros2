import * as THREE from "three";
import { ColladaLoader } from "three/examples/jsm/loaders/ColladaLoader.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import URDFLoader, { type URDFJoint, type URDFRobot } from "urdf-loader";
import type {
  JointLimitRange,
  JointLimitWarning,
  JointTuple6,
} from "../transports/types";
import {
  M0609_JOINT_NAMES,
  RG2_MASTER_JOINT_NAME,
  RG2_MAX_WIDTH_MM,
  clampJointValue,
  clampRg2WidthMm,
  rg2WidthMmToJointRad,
} from "./math";

export interface M0609RigOptions {
  assetsBaseUrl: string;
  urdfFileName?: string;
  clampToLimits?: boolean;
  showAxes?: boolean;
}

const DEFAULT_LIMIT: JointLimitRange = {
  lowerRad: -2 * Math.PI,
  upperRad: 2 * Math.PI,
};

/**
 * Loads the Doosan M0609 URDF into a Three.js root group aligned from
 * ROS REP-103 (Z-up) to Three.js scene coordinates (Y-up).
 */
export class M0609RobotRig {
  /** Scene root rotated by -90 deg around X so URDF +Z aligns with Three.js +Y. */
  public readonly rootGroup = new THREE.Group();
  private robot: URDFRobot | null = null;
  private readonly jointLimits = new Map<string, JointLimitRange>();
  private readonly clampToLimits: boolean;
  private baseAxes: THREE.AxesHelper | null = null;
  private eeAxes: THREE.AxesHelper | null = null;
  private currentJointsRad: JointTuple6 = [0, 0, 0, 0, 0, 0];
  private currentGripperWidthMm = RG2_MAX_WIDTH_MM;
  private rg2Limit: JointLimitRange = { lowerRad: 0.0, upperRad: 1.22 };

  constructor(options: Pick<M0609RigOptions, "clampToLimits">) {
    this.clampToLimits = options.clampToLimits ?? true;
    this.rootGroup.name = "doosan_m0609_root";
    // Convert ROS REP-103 (X forward, Y left, Z up) to Three.js (Y up)
    this.rootGroup.rotation.x = -Math.PI / 2;
  }

  async load(options: M0609RigOptions): Promise<void> {
    const base = options.assetsBaseUrl.replace(/\/+$/, "");
    const urdfFile = options.urdfFileName ?? "m0609.urdf";
    const urdfUrl = `${base}/${urdfFile}`;

    const manager = new THREE.LoadingManager();
    const loader = new URDFLoader(manager);
    loader.parseVisual = true;
    loader.parseCollision = false;
    loader.loadMeshCb = (path, loadManager, done) => {
      if (/\.stl$/i.test(path)) {
        const stlLoader = new STLLoader(loadManager);
        stlLoader.load(
          path,
          (geom) => {
            const mesh = new THREE.Mesh(
              geom,
              new THREE.MeshStandardMaterial({ color: 0xe2e8f0, metalness: 0.25, roughness: 0.55 })
            );
            mesh.castShadow = true;
            mesh.receiveShadow = true;
            done(mesh);
          },
          undefined,
          (err) => done(new THREE.Group(), err instanceof Error ? err : new Error(String(err)))
        );
        return;
      }

      if (/\.dae$/i.test(path)) {
        const daeLoader = new ColladaLoader(loadManager);
        daeLoader.load(
          path,
          (dae) => {
            // Strip embedded Blender lights/cameras from official DAE files
            const toRemove: THREE.Object3D[] = [];
            dae.scene.traverse((child) => {
              if ((child as THREE.Light).isLight || (child as THREE.Camera).isCamera) {
                toRemove.push(child);
              } else if ((child as THREE.Mesh).isMesh) {
                child.castShadow = true;
                child.receiveShadow = true;
              }
            });
            for (const obj of toRemove) {
              obj.parent?.remove(obj);
            }
            done(dae.scene);
          },
          undefined,
          (err) => done(new THREE.Group(), err instanceof Error ? err : new Error(String(err)))
        );
        return;
      }

      done(new THREE.Group(), new Error(`Unsupported mesh format: ${path}`));
    };

    let pendingMeshes = 0;
    const origLoadMeshCb = loader.loadMeshCb;
    loader.loadMeshCb = (path, loadManager, done) => {
      pendingMeshes += 1;
      origLoadMeshCb(path, loadManager, (obj, err) => {
        pendingMeshes = Math.max(0, pendingMeshes - 1);
        done(obj, err);
      });
    };

    const robot = await new Promise<URDFRobot>((resolve, reject) => {
      let settled = false;
      let loadedRobot: URDFRobot | null = null;

      const finish = () => {
        if (!settled && loadedRobot) {
          settled = true;
          resolve(loadedRobot);
        }
      };

      manager.onLoad = finish;

      manager.onError = (url) => {
        if (!settled) {
          settled = true;
          reject(new Error(`Failed to load robot asset: ${url}`));
        }
      };

      loader.load(
        urdfUrl,
        (parsed) => {
          loadedRobot = parsed;
          if (pendingMeshes === 0) {
            finish();
          }
        },
        undefined,
        (err) => {
          if (!settled) {
            settled = true;
            reject(err instanceof Error ? err : new Error(String(err)));
          }
        }
      );
    });

    this.disposeRobot();
    this.robot = robot;
    this.rootGroup.add(robot);

    this.jointLimits.clear();
    for (const jName of M0609_JOINT_NAMES) {
      const joint: URDFJoint | undefined = robot.joints[jName];
      if (joint && joint.limit && joint.limit.upper > joint.limit.lower) {
        this.jointLimits.set(jName, {
          lowerRad: joint.limit.lower,
          upperRad: joint.limit.upper,
        });
      } else {
        this.jointLimits.set(jName, DEFAULT_LIMIT);
      }
    }

    const rg2Joint: URDFJoint | undefined = robot.joints[RG2_MASTER_JOINT_NAME];
    if (rg2Joint && rg2Joint.limit && rg2Joint.limit.upper > rg2Joint.limit.lower) {
      this.rg2Limit = {
        lowerRad: rg2Joint.limit.lower,
        upperRad: Math.min(rg2Joint.limit.upper, 1.22),
      };
    } else {
      this.rg2Limit = { lowerRad: 0.0, upperRad: 1.22 };
    }

    this.attachAxesHelpers(options.showAxes ?? true);
    this.applyJointsRad(this.currentJointsRad);
    this.applyGripperWidthMm(this.currentGripperWidthMm);
  }

  private attachAxesHelpers(visible: boolean): void {
    if (!this.robot) return;
    if (!this.baseAxes) {
      this.baseAxes = new THREE.AxesHelper(0.18);
      this.baseAxes.name = "base_axes";
      this.robot.add(this.baseAxes);
    }
    this.baseAxes.visible = visible;

    const tcpTarget =
      this.robot.links["rg2_gripper_grasp_frame"] ?? this.robot.links["link_6"];
    if (tcpTarget && !this.eeAxes) {
      this.eeAxes = new THREE.AxesHelper(0.14);
      this.eeAxes.name = "ee_axes";
      tcpTarget.add(this.eeAxes);
    }
    if (this.eeAxes) {
      this.eeAxes.visible = visible;
    }
  }

  setShowAxes(visible: boolean): void {
    if (this.baseAxes) this.baseAxes.visible = visible;
    if (this.eeAxes) this.eeAxes.visible = visible;
  }

  /**
   * Apply 6 joint angles in radians and return any near-limit warnings (>= 90% range).
   */
  applyJointsRad(jointsRad: JointTuple6): JointLimitWarning[] {
    const warnings: JointLimitWarning[] = [];
    const applied: JointTuple6 = [...jointsRad];

    for (let i = 0; i < M0609_JOINT_NAMES.length; i++) {
      const jName = M0609_JOINT_NAMES[i];
      const limit = this.jointLimits.get(jName) ?? DEFAULT_LIMIT;
      const val = this.clampToLimits
        ? clampJointValue(jointsRad[i], limit)
        : jointsRad[i];
      applied[i] = val;

      const halfSpan = (limit.upperRad - limit.lowerRad) / 2;
      const center = (limit.upperRad + limit.lowerRad) / 2;
      if (halfSpan > 0) {
        const utilization = Math.abs(val - center) / halfSpan;
        if (utilization >= 0.9) {
          warnings.push({
            jointName: jName,
            valueRad: val,
            lowerRad: limit.lowerRad,
            upperRad: limit.upperRad,
            utilization,
          });
        }
      }

      if (this.robot && this.robot.joints[jName]) {
        this.robot.joints[jName].setJointValue(val);
      }
    }

    this.currentJointsRad = applied;
    return warnings;
  }

  getCurrentJointsRad(): JointTuple6 {
    return [...this.currentJointsRad];
  }

  /**
   * Apply RG2 finger opening width in millimeters [0, 110].
   * Drives the master joint (`rg2_gripper_joint`) and all URDF mimic joints symmetrically.
   */
  applyGripperWidthMm(widthMm: number): number {
    const clampedMm = clampRg2WidthMm(widthMm);
    const q = rg2WidthMmToJointRad(clampedMm, this.rg2Limit);
    this.currentGripperWidthMm = clampedMm;

    if (this.robot && this.robot.joints[RG2_MASTER_JOINT_NAME]) {
      this.robot.joints[RG2_MASTER_JOINT_NAME].setJointValue(q);
    }
    return clampedMm;
  }

  getCurrentGripperWidthMm(): number {
    return this.currentGripperWidthMm;
  }

  private disposeRobot(): void {
    if (!this.robot) return;
    this.robot.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (mesh.geometry) {
        mesh.geometry.dispose();
      }
      const mat = mesh.material;
      if (Array.isArray(mat)) {
        for (const m of mat) disposeMaterial(m);
      } else if (mat) {
        disposeMaterial(mat);
      }
    });
    this.rootGroup.remove(this.robot);
    this.robot = null;
    this.baseAxes = null;
    this.eeAxes = null;
  }

  dispose(): void {
    this.disposeRobot();
  }
}

function disposeMaterial(mat: THREE.Material): void {
  const rec = mat as unknown as Record<string, unknown>;
  for (const key of Object.keys(rec)) {
    const val = rec[key];
    if (val && typeof val === "object" && (val as THREE.Texture).isTexture) {
      (val as THREE.Texture).dispose();
    }
  }
  mat.dispose();
}
