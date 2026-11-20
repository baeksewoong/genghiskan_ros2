import * as THREE from "three";

/**
 * Simplified schematic furniture for the robot cell: a workbench (작업대) to
 * the viewer's left and a loading rack (적재대) to the right, modeled after the
 * physical cell (Lego-Duplo-style colored riser legs on a green mat, stacked
 * acrylic/foam trays). The workbench's top tray is the receiving tray (수령대)
 * where finished items are placed, so it gets a distinct highlight color.
 *
 * Positioned directly in THREE world space (Y-up), matching the ground grid
 * and camera presets in viewer.ts -- not parented under the ROS-frame robot
 * rig. With the default "front" camera preset (eye +X looking toward -X,
 * up +Y), the viewer's left is +Z and right is -Z, so the workbench sits
 * at +Z and the loading rack at -Z.
 */

const LEG_COLORS = [0xdc2626, 0xfacc15, 0x2563eb, 0xfacc15] as const; // red/yellow/blue/yellow Lego-Duplo studs
const MAT_GREEN = 0x16a34a;
const TRAY_ACRYLIC = 0x7dd3fc;
const TRAY_WHITE = 0xe2e8f0;
const RECEIVING_TRAY = 0xfef3c7; // foam board receiving tray (수령대) highlight

interface TierSpec {
  baseY: number;
  legHeight: number;
  trayThickness: number;
  trayColor: number;
  trayOpacity?: number;
  width: number;
  depth: number;
}

function addMat(group: THREE.Group, centerX: number, centerZ: number, width: number, depth: number): void {
  const mat = new THREE.Mesh(
    new THREE.BoxGeometry(width, 0.006, depth),
    new THREE.MeshStandardMaterial({ color: MAT_GREEN, roughness: 0.85 })
  );
  mat.position.set(centerX, 0.003, centerZ);
  mat.receiveShadow = true;
  mat.name = "station_mat";
  group.add(mat);
}

function addTier(group: THREE.Group, centerX: number, centerZ: number, tier: TierSpec, legColorOffset: number): void {
  const legSize = 0.022;
  const halfW = tier.width / 2 - legSize;
  const halfD = tier.depth / 2 - legSize;
  const legCorners: [number, number][] = [
    [-halfW, -halfD],
    [halfW, -halfD],
    [-halfW, halfD],
    [halfW, halfD],
  ];

  legCorners.forEach(([dx, dz], i) => {
    const leg = new THREE.Mesh(
      new THREE.BoxGeometry(legSize, tier.legHeight, legSize),
      new THREE.MeshStandardMaterial({
        color: LEG_COLORS[(i + legColorOffset) % LEG_COLORS.length],
        roughness: 0.55,
      })
    );
    leg.position.set(centerX + dx, tier.baseY + tier.legHeight / 2, centerZ + dz);
    leg.castShadow = true;
    leg.receiveShadow = true;
    leg.name = "station_leg";
    group.add(leg);
  });

  const trayY = tier.baseY + tier.legHeight + tier.trayThickness / 2;
  const trayMaterial = new THREE.MeshStandardMaterial({
    color: tier.trayColor,
    roughness: 0.3,
    transparent: tier.trayOpacity !== undefined,
    opacity: tier.trayOpacity ?? 1,
  });
  const tray = new THREE.Mesh(new THREE.BoxGeometry(tier.width, tier.trayThickness, tier.depth), trayMaterial);
  tray.position.set(centerX, trayY, centerZ);
  tray.castShadow = true;
  tray.receiveShadow = true;
  tray.name = "station_tray";
  group.add(tray);
}

function buildLoadingRack(): THREE.Group {
  const group = new THREE.Group();
  group.name = "loading_rack";
  const width = 0.3;
  const depth = 0.26;
  addMat(group, 0, 0, width + 0.04, depth + 0.04);

  const tiers: TierSpec[] = [
    { baseY: 0, legHeight: 0.13, trayThickness: 0.012, trayColor: TRAY_ACRYLIC, trayOpacity: 0.55, width, depth },
    { baseY: 0.142, legHeight: 0.13, trayThickness: 0.012, trayColor: TRAY_ACRYLIC, trayOpacity: 0.55, width, depth },
  ];
  tiers.forEach((tier, i) => addTier(group, 0, 0, tier, i));
  return group;
}

function buildWorkbench(): THREE.Group {
  const group = new THREE.Group();
  group.name = "workbench";
  const width = 0.34;
  const depth = 0.3;
  addMat(group, 0, 0, width + 0.04, depth + 0.04);

  const shelfTiers: TierSpec[] = [
    { baseY: 0, legHeight: 0.1, trayThickness: 0.012, trayColor: TRAY_WHITE, width, depth },
    { baseY: 0.112, legHeight: 0.1, trayThickness: 0.012, trayColor: TRAY_WHITE, width, depth },
    { baseY: 0.224, legHeight: 0.1, trayThickness: 0.012, trayColor: TRAY_WHITE, width, depth },
  ];
  shelfTiers.forEach((tier, i) => addTier(group, 0, 0, tier, i));

  // Top tier: the receiving tray (수령대) -- a wider foam board, highlighted.
  const receivingWidth = width + 0.05;
  const receivingDepth = depth + 0.03;
  addTier(
    group,
    0,
    0,
    {
      baseY: 0.336,
      legHeight: 0.08,
      trayThickness: 0.022,
      trayColor: RECEIVING_TRAY,
      width: receivingWidth,
      depth: receivingDepth,
    },
    3
  );

  // Thin emissive edge outline around the receiving tray so it reads as the pickup point.
  const edgeY = 0.336 + 0.08 + 0.022;
  const outline = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(receivingWidth, 0.001, receivingDepth)),
    new THREE.LineBasicMaterial({ color: 0xfbbf24 })
  );
  outline.position.set(0, edgeY, 0);
  outline.name = "receiving_tray_outline";
  group.add(outline);

  return group;
}

/**
 * Owns the loading-rack (left) and workbench+receiving-tray (right) meshes.
 */
export class SceneStations {
  public readonly group = new THREE.Group();
  public readonly loadingRack: THREE.Group;
  public readonly workbench: THREE.Group;

  constructor(options: { loadingRackOffset?: [number, number]; workbenchOffset?: [number, number] } = {}) {
    this.group.name = "scene_stations";

    this.loadingRack = buildLoadingRack();
    const [lrX, lrZ] = options.loadingRackOffset ?? [0.9, -0.32];
    this.loadingRack.position.set(lrX, 0, lrZ);
    this.group.add(this.loadingRack);

    this.workbench = buildWorkbench();
    const [wbX, wbZ] = options.workbenchOffset ?? [0.9, 0.22];
    this.workbench.position.set(wbX, 0, wbZ);
    this.group.add(this.workbench);
  }

  setVisible(visible: boolean): void {
    this.group.visible = visible;
  }

  dispose(): void {
    this.group.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (mesh.geometry) mesh.geometry.dispose();
      const mat = mesh.material;
      if (Array.isArray(mat)) {
        mat.forEach((m) => m.dispose());
      } else if (mat) {
        (mat as THREE.Material).dispose();
      }
    });
  }
}
