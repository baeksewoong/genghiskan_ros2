import { Pill } from "../atoms/Pill";
import { StepButton } from "../atoms/StepButton";
import type { GripperAction } from "../../types";

const GRIPPER_STATE_LABEL: Record<GripperAction, string> = {
  OPEN: "열림",
  CLOSE: "닫힘",
};

interface GripperControlsProps {
  gripperState: GripperAction | null;
  pending: boolean;
  disabled: boolean;
  onOpen: () => void;
  onClose: () => void;
}

/** 그리퍼 열기/닫기(TP-12) + 상태 표시(TP-13, 완료 이벤트 수신 시만 갱신 — 파지 성공
 * 여부 판정은 범위 밖). 조그와 동일한 상호 배제 규칙을 따르므로 pending/disabled는
 * page가 조그 pending과 합쳐서 내려준다. */
export function GripperControls({ gripperState, pending, disabled, onOpen, onClose }: GripperControlsProps) {
  return (
    <section className="panel tp-gripper-panel">
      <h2>그리퍼</h2>
      <p className="tp-gripper-state">
        현재 상태:{" "}
        <Pill variant={gripperState ? "ok" : "neutral"}>
          {gripperState ? GRIPPER_STATE_LABEL[gripperState] : "알 수 없음"}
        </Pill>
      </p>
      <div className="tp-gripper-row">
        <StepButton disabled={disabled} pending={pending} onClick={onOpen}>
          열기
        </StepButton>
        <StepButton disabled={disabled} pending={pending} onClick={onClose}>
          닫기
        </StepButton>
      </div>
    </section>
  );
}
