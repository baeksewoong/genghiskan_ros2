import { useEffect, useRef, useState } from "react";
import { api, TeachingPendantError } from "../lib/api";
import type { GripperAction, JogAxis, JogRefFrame, JogSpace } from "../types";
import type { TeachingPendantState } from "./useLiveState";

const CARTESIAN_AXES: JogAxis[] = ["X", "Y", "Z", "RX", "RY", "RZ"];
const JOINT_AXES: JogAxis[] = ["J1", "J2", "J3", "J4", "J5", "J6"];
const LINEAR_AXES: JogAxis[] = ["X", "Y", "Z"];
// TP-11: 완료/실패 응답이 이 시간 내 오지 않으면 타임아웃 에러를 띄운다.
const RESPONSE_TIMEOUT_MS = 10000;

export interface UseTeachingPendantControlsArgs {
  connected: boolean;
  teachingPendant: TeachingPendantState;
  beginTeachingPendantJog: (jogId: string) => void;
  beginTeachingPendantGripper: (cmdId: string) => void;
  timeoutTeachingPendantJog: (jogId: string) => void;
  timeoutTeachingPendantGripper: (cmdId: string) => void;
  reportTeachingPendantError: (message: string, code?: string) => void;
}

/** 티칭 팬던트(실물 로봇 조그 제어)의 state + 핸들러를 소유하는 공유 훅
 * (PRD: assets/docs/prd-teaching-pendant.md). `TeachingPendantPage`와
 * `DashboardPage`(홈 임베드) 양쪽에서 재사용한다 — 두 page 모두 자신의
 * `useLiveState()` 호출 결과 중 티칭 팬던트 관련 조각을 그대로 넘겨준다
 * (이 훅이 두 번째 WebSocket 연결을 만들지 않도록, useLiveState()는 이 훅 안에서
 * 다시 부르지 않는다). */
export function useTeachingPendantControls({
  connected,
  teachingPendant,
  beginTeachingPendantJog,
  beginTeachingPendantGripper,
  timeoutTeachingPendantJog,
  timeoutTeachingPendantGripper,
  reportTeachingPendantError,
}: UseTeachingPendantControlsArgs) {
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

  // 3장/9장: 세션 비활성이거나 서버 연결이 끊기면 방향키·그리퍼 버튼을 전부 막는다(요구사항 10).
  // 로봇과는 SQS로만 통신하므로 별도 "로봇 연결" 조건은 없다.
  const controlsDisabled = !teachingPendant.enabled || !connected;
  // 8.2 스텝 상호 배제: 조그/그리퍼 중 하나라도 응답 대기 중이면 둘 다 새 요청을 막는다.
  const jogOrGripperBusy = teachingPendant.jogPending || teachingPendant.gripperPending;
  const jogAxes = mode === "TASK" ? CARTESIAN_AXES : JOINT_AXES;

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

  return {
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
  };
}
