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
  /** Footprint used for leg corner placement; defaults to width/depth. Set smaller than the
   * tray so it can cantilever past its own legs (e.g. an overhanging receiving tray). */
  legFootprintWidth?: number;
  legFootprintDepth?: number;
  /** Leg center offset relative to the tray's center passed into addTier(); defaults to 0
   * (legs centered under the tray). Use to land legs on the support below instead of
   * following the tray out over an overhang. */
  legOffsetX?: number;
  legOffsetZ?: number;
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
  const legFootprintWidth = tier.legFootprintWidth ?? tier.width;
  const legFootprintDepth = tier.legFootprintDepth ?? tier.depth;
  const legCenterX = centerX + (tier.legOffsetX ?? 0);
  const legCenterZ = centerZ + (tier.legOffsetZ ?? 0);
  const halfW = legFootprintWidth / 2 - legSize;
  const halfD = legFootprintDepth / 2 - legSize;
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
    leg.position.set(legCenterX + dx, tier.baseY + tier.legHeight / 2, legCenterZ + dz);
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

  // 1/2/3층 받침판 윗면 = LOAD1 해당 층 그리퍼 닫는 높이에 맞춤.
  // poses.START_POS_PICK_X[n] Z(플랜지) -> URDF FK상 grasp frame은 약 7.4mm 아래,
  // 판재(두께 1mm) 중심을 잡으므로 받침판 윗면 = grasp Z - 0.5mm.
  //   1층: 155.58 -> 148.2 -> 147.7mm,  2층: 248.13 -> 240.7 -> 240.2mm,
  //   3층: 340.63 -> 333.2 -> 332.7mm
  const trayThickness = 0.012;
  const tier1TopY = 0.1477;
  const tier2TopY = 0.2402;
  const tier3TopY = 0.3327;
  const tiers: TierSpec[] = [
    { baseY: 0, legHeight: tier1TopY - trayThickness, trayThickness, trayColor: TRAY_ACRYLIC, trayOpacity: 0.55, width, depth },
    {
      baseY: tier1TopY,
      legHeight: tier2TopY - trayThickness - tier1TopY,
      trayThickness,
      trayColor: TRAY_ACRYLIC,
      trayOpacity: 0.55,
      width,
      depth,
    },
    {
      baseY: tier2TopY,
      legHeight: tier3TopY - trayThickness - tier2TopY,
      trayThickness,
      trayColor: TRAY_ACRYLIC,
      trayOpacity: 0.55,
      width,
      depth,
    },
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

  // 1/2/3층 선반 윗면 = UNLOAD1 해당 층 그리퍼 닫는 높이에 맞춤.
  // unload_poses.UNLOAD_J 6/5/4번(언로드1/2/3) posj -> URDF FK상 grasp frame Z,
  // 판(두께 1mm) 중심을 잡으므로 선반 윗면 = grasp Z - 0.5mm.
  //   1층: 88.8 -> 88.3mm,  2층: 154.9 -> 154.4mm,  3층: 220.1 -> 219.6mm
  const shelfThickness = 0.012;
  const shelfTopY = [0.0883, 0.1544, 0.2196];
  const shelfTiers: TierSpec[] = shelfTopY.map((topY, i) => {
    const baseY = i === 0 ? 0 : shelfTopY[i - 1];
    return {
      baseY,
      legHeight: topY - shelfThickness - baseY,
      trayThickness: shelfThickness,
      trayColor: TRAY_WHITE,
      width,
      depth,
    };
  });
  shelfTiers.forEach((tier, i) => addTier(group, 0, 0, tier, i));

  // Top tier: the receiving tray (수령대) -- a foam board roughly 2x the stack's
  // length, overhanging only toward the back (away from the robot, +X) so its
  // front edge stays flush with the shelves below, matching the reference photo.
  // Its 4 support legs stay on tier3's own footprint (legOffsetX cancels the tray's
  // backward shift) so none of them dangle in the air under the overhang -- the
  // board cantilevers off the workbench stack instead.
  const receivingWidth = width * 2;
  const receivingDepth = depth + 0.03;
  const receivingCenterX = (receivingWidth - width) / 2;
  // 수령대 윗면 = 3층 선반 윗면 + 선반 층 간격(1~3층 윗면 간격 평균, 약 65.7mm) -> 약 285.3mm.
  const receivingBaseY = shelfTopY[shelfTopY.length - 1];
  const shelfPitch = (receivingBaseY - shelfTopY[0]) / (shelfTopY.length - 1);
  const receivingThickness = 0.022;
  const receivingTopY = receivingBaseY + shelfPitch;
  const receivingLegHeight = receivingTopY - receivingThickness - receivingBaseY;
  addTier(
    group,
    receivingCenterX,
    0,
    {
      baseY: receivingBaseY,
      legHeight: receivingLegHeight,
      trayThickness: receivingThickness,
      trayColor: RECEIVING_TRAY,
      width: receivingWidth,
      depth: receivingDepth,
      legFootprintWidth: width,
      legFootprintDepth: depth,
      legOffsetX: -receivingCenterX,
    },
    3
  );

  // Thin emissive edge outline around the receiving tray so it reads as the pickup point.
  const edgeY = receivingTopY;
  const outline = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(receivingWidth, 0.001, receivingDepth)),
    new THREE.LineBasicMaterial({ color: 0xfbbf24 })
  );
  outline.position.set(receivingCenterX, edgeY, 0);
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
    const [lrX, lrZ] = options.loadingRackOffset ?? [0.85, -0.17];
    this.loadingRack.position.set(lrX, 0, lrZ);
    this.group.add(this.loadingRack);

    this.workbench = buildWorkbench();
    const [wbX, wbZ] = options.workbenchOffset ?? [0.95, 0.22];
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
