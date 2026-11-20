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
 *
 * 위치와 층 높이는 실제 로봇 좌표(sfarm_robot/poses.py)에서 계산한다 (REAL_* 아래).
 * 로봇 베이스 = THREE 원점, ROS (x, y, z) mm -> THREE (x, z, -y) m (robot_rig.ts의 -90도 X 회전과 같음).
 */

// ---- 실제 로봇 좌표 (로봇 베이스 기준 mm, 2026-11-20 poses.py / 실제 로봇 실측)
/** 적재대 잡는 위치 START_POS_PICK_X[1..3] (TCP = 판재 앞 손잡이). */
const REAL_RACK_PICK_MM: [number, number, number][] = [
  [464.83, 182.87, 155.58], // 1층
  [464.81, 189.08, 248.1], // 2층
  [464.81, 189.08, 340.6], // 3층
];
/** 작업대(sd) 넣기 끝 위치 = 판재를 놓는 곳 (TCP = 판재 앞 손잡이). 1층은 다가가기 끝, 2, 3층은 SD_INSERT_DONE_X. */
const REAL_SD_PLACE_MM: [number, number, number][] = [
  [583.8, -189.7, 110.0], // 1층
  [563.53, -193.96, 164.96], // 2층
  [574.0, -168.6, 305.6], // 3층
];
/** 잡는 TCP가 판(tray) 윗면보다 얼마나 위인지 (mm). 손잡이 높이에 맞춰 조정. */
const TCP_ABOVE_TRAY_MM = 10;
/** 판 앞쪽 끝(로봇 쪽)이 잡는 TCP X보다 얼마나 앞인지 (mm, +면 로봇에서 더 멀리). */
const TRAY_FRONT_FROM_TCP_MM = 0;

const mean = (v: number[]): number => v.reduce((a, b) => a + b, 0) / v.length;
/** 판 윗면 높이들(m) -> 층별 TierSpec (다리는 아래 판 윗면에서 이 판 아랫면까지). */
function tiersFromTops(topsM: number[], spec: Omit<TierSpec, "baseY" | "legHeight">): TierSpec[] {
  let prevTop = 0;
  return topsM.map((top) => {
    const tier = { ...spec, baseY: prevTop, legHeight: Math.max(0.005, top - spec.trayThickness - prevTop) };
    prevTop = top;
    return tier;
  });
}
const trayTopsM = (pts: [number, number, number][]): number[] => pts.map((p) => (p[2] - TCP_ABOVE_TRAY_MM) / 1000);
/** 판 가운데의 THREE (X, Z): 앞쪽 끝 = TCP X (+여유), 가운데 = 앞 + 판 길이(X) / 2. */
function stationCenter(pts: [number, number, number][], trayWidthM: number): [number, number] {
  const frontX = (mean(pts.map((p) => p[0])) + TRAY_FRONT_FROM_TCP_MM) / 1000;
  return [frontX + trayWidthM / 2, -mean(pts.map((p) => p[1])) / 1000];
}

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

const RACK_WIDTH_M = 0.3; // X (로봇에서 멀어지는 방향, 판재 길이 방향)
const WORKBENCH_WIDTH_M = 0.34;

function buildLoadingRack(): THREE.Group {
  const group = new THREE.Group();
  group.name = "loading_rack";
  const width = RACK_WIDTH_M;
  const depth = 0.26;
  addMat(group, 0, 0, width + 0.04, depth + 0.04);

  // 층 높이 = 실제 잡는 위치 Z - TCP_ABOVE_TRAY_MM
  const tiers = tiersFromTops(trayTopsM(REAL_RACK_PICK_MM), {
    trayThickness: 0.012,
    trayColor: TRAY_ACRYLIC,
    trayOpacity: 0.55,
    width,
    depth,
  });
  tiers.forEach((tier, i) => addTier(group, 0, 0, tier, i));
  return group;
}

function buildWorkbench(): THREE.Group {
  const group = new THREE.Group();
  group.name = "workbench";
  const width = WORKBENCH_WIDTH_M;
  const depth = 0.3;
  addMat(group, 0, 0, width + 0.04, depth + 0.04);

  // 판 3장 높이 = 실제 sd 1~3층 놓는 위치 Z - TCP_ABOVE_TRAY_MM
  const shelfTops = trayTopsM(REAL_SD_PLACE_MM);
  const shelfTiers = tiersFromTops(shelfTops, { trayThickness: 0.012, trayColor: TRAY_WHITE, width, depth });
  const topShelf = shelfTops[shelfTops.length - 1];
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
  addTier(
    group,
    receivingCenterX,
    0,
    {
      baseY: topShelf,
      legHeight: 0.08,
      trayThickness: 0.022,
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
  const edgeY = topShelf + 0.08 + 0.022;
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
    const [lrX, lrZ] = options.loadingRackOffset ?? stationCenter(REAL_RACK_PICK_MM, RACK_WIDTH_M);
    this.loadingRack.position.set(lrX, 0, lrZ);
    this.group.add(this.loadingRack);

    this.workbench = buildWorkbench();
    const [wbX, wbZ] = options.workbenchOffset ?? stationCenter(REAL_SD_PLACE_MM, WORKBENCH_WIDTH_M);
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
