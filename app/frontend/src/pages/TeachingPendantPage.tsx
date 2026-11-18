import { TeachingPendantTemplate } from "../components/templates/TeachingPendantTemplate";
import { DoosanM0609Viewer } from "../components/organisms/DoosanArmViewer/DoosanArmViewer";
import { DOOSAN_HOME_POSES_DEG } from "../components/organisms/DoosanArmViewer";
import { RemoteControlPanel } from "../components/organisms/RemoteControlPanel";
import { useLiveState } from "../hooks/useLiveState";
import { useTeachingPendantControls } from "../hooks/useTeachingPendantControls";

/** 티칭 팬던트(실물 로봇 조그 제어) 페이지 (PRD: assets/docs/prd-teaching-pendant.md). 이 페이지가
 * API 호출과 상태 소유를 전부 가지고, organism들에는 props로만 내려준다. 실제 로직은
 * `useTeachingPendantControls()`에 있다 — 홈 대시보드와 동일한 3D 뷰어 + 리모컨 레이아웃을
 * 이 페이지로 옮겨왔다(홈 대시보드에는 더 이상 표시하지 않음). */
export function TeachingPendantPage() {
  const {
    connected,
    teachingPendant,
    beginTeachingPendantJog,
    beginTeachingPendantGripper,
    timeoutTeachingPendantJog,
    timeoutTeachingPendantGripper,
    reportTeachingPendantError,
    acknowledgeTeachingPendantError,
  } = useLiveState();

  const {
    mode,
    setMode,
    refFrame,
    setRefFrame,
    stepLinearMm,
    setStepLinearMm,
    stepRotationalDeg,
    setStepRotationalDeg,
    stepJointDeg,
    setStepJointDeg,
    activationError,
    stopping,
    controlsDisabled,
    jogOrGripperBusy,
    jogAxes,
    handleEnable,
    handleDisable,
    handleJog,
    handleGripper,
    handleStop,
  } = useTeachingPendantControls({
    connected,
    teachingPendant,
    beginTeachingPendantJog,
    beginTeachingPendantGripper,
    timeoutTeachingPendantJog,
    timeoutTeachingPendantGripper,
    reportTeachingPendantError,
  });

  // 조그 중인 실제 로봇의 관절각(posj, deg)을 그대로 3D 뷰어에 반영한다.
  // posx(TASK 공간)는 joint 입력이 아니므로 사용하지 않는다.
  // 아직 조그 중이 아니면(JOINT 포즈 없음) 두산 표준 홈(ready) 자세를 기본값으로 보여준다.
  const liveJoints =
    teachingPendant.currentPose?.space === "JOINT" ? teachingPendant.currentPose.posj : DOOSAN_HOME_POSES_DEG.ready;

  return (
    <TeachingPendantTemplate
      armViewer={
        <section className="panel arm-viewer-panel">
          <h2>M0609 3D 뷰어</h2>
          <DoosanM0609Viewer
            assetsBaseUrl="/assets/doosan/m0609_rg2"
            gripper="rg2"
            joints={liveJoints}
            angleUnit="deg"
            showHomeButton={false}
            showGripperControls={false}
          />
        </section>
      }
      remoteControl={
        <RemoteControlPanel
          enabled={teachingPendant.enabled}
          owner={teachingPendant.owner}
          activationError={activationError}
          onEnable={handleEnable}
          onDisable={handleDisable}
          wsConnected={connected}
          currentPose={teachingPendant.currentPose}
          poseError={teachingPendant.lastError}
          onAcknowledgeError={acknowledgeTeachingPendantError}
          mode={mode}
          refFrame={refFrame}
          stepLinearMm={stepLinearMm}
          stepRotationalDeg={stepRotationalDeg}
          stepJointDeg={stepJointDeg}
          controlsDisabled={controlsDisabled}
          onChangeMode={setMode}
          onChangeRefFrame={setRefFrame}
          onChangeStepLinearMm={setStepLinearMm}
          onChangeStepRotationalDeg={setStepRotationalDeg}
          onChangeStepJointDeg={setStepJointDeg}
          jogAxes={jogAxes}
          jogOrGripperBusy={jogOrGripperBusy}
          jogPending={teachingPendant.jogPending}
          onJog={handleJog}
          gripperState={teachingPendant.gripperState}
          gripperPending={teachingPendant.gripperPending}
          onGripperOpen={() => handleGripper("OPEN")}
          onGripperClose={() => handleGripper("CLOSE")}
          stopping={stopping}
          onStop={handleStop}
        />
      }
    />
  );
}
