import { Tabs } from "../molecules/Tabs";
import { TeachingPendantActivationPanel } from "./TeachingPendantActivationPanel";
import { RobotPoseStatusPanel } from "./RobotPoseStatusPanel";
import { JogModeControls } from "./JogModeControls";
import { JogPad } from "./JogPad";
import { GripperControls } from "./GripperControls";
import { StopControl } from "./StopControl";
import type { GripperAction, JogAxis, JogRefFrame, JogSpace, TeachingPendantPose } from "../../types";
import type { TeachingPendantErrorInfo } from "../../hooks/useLiveState";

interface RemoteControlPanelProps {
  // 활성화 / 상태 탭
  enabled: boolean;
  owner: string | null;
  activationError: string | null;
  onEnable: () => Promise<boolean>;
  onDisable: () => void;
  wsConnected: boolean;
  currentPose: TeachingPendantPose | null;
  poseError: TeachingPendantErrorInfo | null;
  onAcknowledgeError: () => void;
  // 조그 탭 (모드/스텝 + 패드)
  mode: JogSpace;
  refFrame: JogRefFrame;
  stepLinearMm: number;
  stepRotationalDeg: number;
  stepJointDeg: number;
  controlsDisabled: boolean;
  onChangeMode: (mode: JogSpace) => void;
  onChangeRefFrame: (refFrame: JogRefFrame) => void;
  onChangeStepLinearMm: (mm: number) => void;
  onChangeStepRotationalDeg: (deg: number) => void;
  onChangeStepJointDeg: (deg: number) => void;
  jogAxes: JogAxis[];
  jogOrGripperBusy: boolean;
  jogPending: boolean;
  onJog: (axis: JogAxis, direction: 1 | -1) => void;
  // 그리퍼 탭
  gripperState: GripperAction | null;
  gripperPending: boolean;
  onGripperOpen: () => void;
  onGripperClose: () => void;
  // 정지 — 탭과 무관하게 항상 보여야 하는 안전 제어
  stopping: boolean;
  onStop: () => void;
}

/** 3D 뷰어 오른쪽에 나란히 붙는 "리모컨" 패널. 기존 6개 organism(활성화/포즈 상태/
 * 조그 모드/조그 패드/그리퍼/정지)을 탭으로 구분해 묶기만 하고, 데이터와 콜백은 전부
 * props로 주입받는다 — 이 organism 안에서 api.*나 useLiveState()를 직접 호출하지
 * 않는다. 정지는 안전상 탭 전환과 무관하게 항상 눌릴 수 있어야 하므로 탭 밖에
 * 고정한다. */
export function RemoteControlPanel({
  enabled,
  owner,
  activationError,
  onEnable,
  onDisable,
  wsConnected,
  currentPose,
  poseError,
  onAcknowledgeError,
  mode,
  refFrame,
  stepLinearMm,
  stepRotationalDeg,
  stepJointDeg,
  controlsDisabled,
  onChangeMode,
  onChangeRefFrame,
  onChangeStepLinearMm,
  onChangeStepRotationalDeg,
  onChangeStepJointDeg,
  jogAxes,
  jogOrGripperBusy,
  jogPending,
  onJog,
  gripperState,
  gripperPending,
  onGripperOpen,
  onGripperClose,
  stopping,
  onStop,
}: RemoteControlPanelProps) {
  return (
    <section className="remote-control-panel">
      <div className="remote-control-bezel">
        <Tabs
          tabs={[
            {
              id: "status",
              label: "상태",
              content: (
                <>
                  <TeachingPendantActivationPanel
                    enabled={enabled}
                    owner={owner}
                    error={activationError}
                    onEnable={onEnable}
                    onDisable={onDisable}
                  />
                  <RobotPoseStatusPanel
                    wsConnected={wsConnected}
                    enabled={enabled}
                    owner={owner}
                    currentPose={currentPose}
                    error={poseError}
                    onAcknowledgeError={onAcknowledgeError}
                  />
                </>
              ),
            },
            {
              id: "jog",
              label: "조그",
              content: (
                <>
                  <JogModeControls
                    mode={mode}
                    refFrame={refFrame}
                    stepLinearMm={stepLinearMm}
                    stepRotationalDeg={stepRotationalDeg}
                    stepJointDeg={stepJointDeg}
                    disabled={controlsDisabled}
                    onChangeMode={onChangeMode}
                    onChangeRefFrame={onChangeRefFrame}
                    onChangeStepLinearMm={onChangeStepLinearMm}
                    onChangeStepRotationalDeg={onChangeStepRotationalDeg}
                    onChangeStepJointDeg={onChangeStepJointDeg}
                  />
                  <JogPad
                    axes={jogAxes}
                    disabled={controlsDisabled || jogOrGripperBusy}
                    pending={jogPending}
                    onJog={onJog}
                  />
                </>
              ),
            },
            {
              id: "gripper",
              label: "그리퍼",
              content: (
                <GripperControls
                  gripperState={gripperState}
                  pending={gripperPending}
                  disabled={controlsDisabled || jogOrGripperBusy}
                  onOpen={onGripperOpen}
                  onClose={onGripperClose}
                />
              ),
            },
          ]}
        />
        <div className="remote-control-stop">
          <StopControl disabled={!enabled} stopping={stopping} onStop={onStop} />
        </div>
      </div>
    </section>
  );
}
