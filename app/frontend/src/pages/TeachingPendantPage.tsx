import { TeachingPendantTemplate } from "../components/templates/TeachingPendantTemplate";
import { RemoteControlPanel } from "../components/organisms/RemoteControlPanel";
import { useLiveState } from "../hooks/useLiveState";
import { useTeachingPendantControls } from "../hooks/useTeachingPendantControls";

/** 티칭 팬던트(실물 로봇 조그 제어) 페이지 (PRD: assets/docs/prd-teaching-pendant.md). 이 페이지가
 * API 호출과 상태 소유를 전부 가지고, organism들에는 props로만 내려준다. 실제 로직은
 * `useTeachingPendantControls()`에 있다. 3D 뷰어(DoosanArmViewer)는 홈 대시보드로 옮겨가
 * 라우트 전환에도 계속 로봇을 따라가도록 바뀌었으므로, 이 페이지는 리모컨 패널만 갖고도
 * 정상 동작한다(뷰어 없음). */
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

  return (
    <TeachingPendantTemplate
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
