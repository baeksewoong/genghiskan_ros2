import { useEffect, useRef, useState } from "react";
import { TeachingPendantTemplate } from "../components/templates/TeachingPendantTemplate";
import { TeachingPendantActivationPanel } from "../components/organisms/TeachingPendantActivationPanel";
import { JogModeControls } from "../components/organisms/JogModeControls";
import { JogPad } from "../components/organisms/JogPad";
import { GripperControls } from "../components/organisms/GripperControls";
import { RobotPoseStatusPanel } from "../components/organisms/RobotPoseStatusPanel";
import { StopControl } from "../components/organisms/StopControl";
import { useLiveState } from "../hooks/useLiveState";
import { api, TeachingPendantError } from "../lib/api";
import type { GripperAction, JogAxis, JogRefFrame, JogSpace } from "../types";

const CARTESIAN_AXES: JogAxis[] = ["X", "Y", "Z", "RX", "RY", "RZ"];
const JOINT_AXES: JogAxis[] = ["J1", "J2", "J3", "J4", "J5", "J6"];
const LINEAR_AXES: JogAxis[] = ["X", "Y", "Z"];
// TP-11: 완료/실패 응답이 이 시간 내 오지 않으면 타임아웃 에러를 띄운다.
const RESPONSE_TIMEOUT_MS = 10000;

/** 티칭 팬던트(실물 로봇 조그 제어) 페이지 — 가상 로봇(/ws/bridge, DashboardPage)과는
 * 완전히 분리된 독립 페이지다(PRD: assets/docs/prd-teaching-pendant.md). 이 페이지가
 * API 호출과 상태 소유를 전부 가지고, organism들에는 props로만 내려준다. */
export function TeachingPendantPage() {
  const {
    snapshot,
    connected,
    teachingPendant,
    beginTeachingPendantJog,
    beginTeachingPendantGripper,
    timeoutTeachingPendantJog,
    timeoutTeachingPendantGripper,
    reportTeachingPendantError,
    acknowledgeTeachingPendantError,
  } = useLiveState();

  const [mode, setMode] = useState<JogSpace>("TASK");
  const [refFrame, setRefFrame] = useState<JogRefFrame>("BASE");
  const [stepLinearMm, setStepLinearMm] = useState(5);
  const [stepRotationalDeg, setStepRotationalDeg] = useState(5);
  const [stepJointDeg, setStepJointDeg] = useState(5);
  const [activationError, setActivationError] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  useEffect(() => {
    return () => {
      timersRef.current.forEach(clearTimeout);
    };
  }, []);

  // 3장/9장: 세션 비활성, ws/로봇 연결 끊김, 로봇 에러 상태면 방향키·그리퍼 버튼을
  // 전부 막는다(요구사항 10).
  const bridgeConnected = snapshot?.robot.bridge_connected ?? false;
  const robotState = snapshot?.robot.state ?? "DISCONNECTED";
  const controlsDisabled =
    !teachingPendant.enabled ||
    !connected ||
    !bridgeConnected ||
    robotState === "ERROR" ||
    robotState === "DISCONNECTED";
  // 8.2 스텝 상호 배제: 조그/그리퍼 중 하나라도 응답 대기 중이면 둘 다 새 요청을 막는다.
  const jogOrGripperBusy = teachingPendant.jogPending || teachingPendant.gripperPending;

  const handleEnable = async (): Promise<boolean> => {
    try {
      setActivationError(null);
      await api.enableTeachingPendant();
      return true;
    } catch (e) {
      setActivationError(e instanceof TeachingPendantError ? e.message : String(e));
      return false;
    }
  };

  const handleDisable = async () => {
    try {
      await api.disableTeachingPendant();
    } catch (e) {
      console.error("티칭 팬던트 비활성화 실패:", e);
    }
  };

  function axisStepSize(axis: JogAxis): number {
    if (mode === "JOINT") return stepJointDeg;
    return LINEAR_AXES.includes(axis) ? stepLinearMm : stepRotationalDeg;
  }

  const handleJog = async (axis: JogAxis, direction: 1 | -1) => {
    if (jogOrGripperBusy || controlsDisabled) return;
    try {
      const { jog_id } = await api.sendJog(
        mode === "TASK"
          ? { space: "TASK", ref_frame: refFrame, axis, direction, step_size: axisStepSize(axis) }
          : { space: "JOINT", axis, direction, step_size: axisStepSize(axis) }
      );
      beginTeachingPendantJog(jog_id);
      timersRef.current.push(setTimeout(() => timeoutTeachingPendantJog(jog_id), RESPONSE_TIMEOUT_MS));
    } catch (e) {
      reportTeachingPendantError(
        e instanceof TeachingPendantError ? e.message : String(e),
        e instanceof TeachingPendantError ? e.errorCode : undefined
      );
    }
  };

  const handleGripper = async (action: GripperAction) => {
    if (jogOrGripperBusy || controlsDisabled) return;
    try {
      const { gripper_cmd_id } = await api.sendGripper(action);
      beginTeachingPendantGripper(gripper_cmd_id);
      timersRef.current.push(setTimeout(() => timeoutTeachingPendantGripper(gripper_cmd_id), RESPONSE_TIMEOUT_MS));
    } catch (e) {
      reportTeachingPendantError(
        e instanceof TeachingPendantError ? e.message : String(e),
        e instanceof TeachingPendantError ? e.errorCode : undefined
      );
    }
  };

  const handleStop = async () => {
    if (stopping) return;
    setStopping(true);
    try {
      // 8.4: 다음 스텝을 막고 ROS 2 쪽에 정지 신호를 전달하는 것까지만 보장한다.
      await api.stopTeachingPendant();
    } catch (e) {
      console.error("정지 요청 실패:", e);
    } finally {
      setStopping(false);
    }
  };

  return (
    <TeachingPendantTemplate
      activation={
        <TeachingPendantActivationPanel
          enabled={teachingPendant.enabled}
          owner={teachingPendant.owner}
          error={activationError}
          onEnable={handleEnable}
          onDisable={handleDisable}
        />
      }
      status={
        <RobotPoseStatusPanel
          wsConnected={connected}
          bridgeConnected={bridgeConnected}
          robotState={robotState}
          enabled={teachingPendant.enabled}
          owner={teachingPendant.owner}
          currentPose={teachingPendant.currentPose}
          error={teachingPendant.lastError}
          onAcknowledgeError={acknowledgeTeachingPendantError}
        />
      }
      modeControls={
        <JogModeControls
          mode={mode}
          refFrame={refFrame}
          stepLinearMm={stepLinearMm}
          stepRotationalDeg={stepRotationalDeg}
          stepJointDeg={stepJointDeg}
          disabled={controlsDisabled}
          onChangeMode={setMode}
          onChangeRefFrame={setRefFrame}
          onChangeStepLinearMm={setStepLinearMm}
          onChangeStepRotationalDeg={setStepRotationalDeg}
          onChangeStepJointDeg={setStepJointDeg}
        />
      }
      gripper={
        <GripperControls
          gripperState={teachingPendant.gripperState}
          pending={teachingPendant.gripperPending}
          disabled={controlsDisabled || jogOrGripperBusy}
          onOpen={() => handleGripper("OPEN")}
          onClose={() => handleGripper("CLOSE")}
        />
      }
      stop={<StopControl disabled={!teachingPendant.enabled} stopping={stopping} onStop={handleStop} />}
      jogPad={
        <JogPad
          axes={mode === "TASK" ? CARTESIAN_AXES : JOINT_AXES}
          disabled={controlsDisabled || jogOrGripperBusy}
          pending={teachingPendant.jogPending}
          onJog={handleJog}
        />
      }
    />
  );
}
