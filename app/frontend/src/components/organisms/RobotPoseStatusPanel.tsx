import { Button } from "../atoms/Button";
import { Pill } from "../atoms/Pill";
import { ConnectionStatus } from "../molecules/ConnectionStatus";
import type { RobotState, TeachingPendantPose } from "../../types";
import type { TeachingPendantErrorInfo } from "../../hooks/useLiveState";

interface RobotPoseStatusPanelProps {
  wsConnected: boolean;
  bridgeConnected: boolean;
  robotState: RobotState;
  enabled: boolean;
  owner: string | null;
  currentPose: TeachingPendantPose | null;
  error: TeachingPendantErrorInfo | null;
  onAcknowledgeError: () => void;
}

function formatPose(pose: TeachingPendantPose): string {
  const values = pose.space === "TASK" ? pose.posx : pose.posj;
  const label = pose.space === "TASK" ? "posx" : "posj";
  if (!values) return `${label}: -`;
  return `${label}: [${values.map((v) => v.toFixed(2)).join(", ")}]`;
}

/** 현재 위치/로봇 상태 표시(TP-07, TP-08) + 조그/그리퍼 에러 배너. 타임아웃(TP-11)처럼
 * pending이 자동으로 풀리지 않는 에러는 "확인"을 눌러야 버튼이 다시 활성화된다. */
export function RobotPoseStatusPanel({
  wsConnected,
  bridgeConnected,
  robotState,
  enabled,
  owner,
  currentPose,
  error,
  onAcknowledgeError,
}: RobotPoseStatusPanelProps) {
  return (
    <section className="panel tp-status-panel">
      <h2>로봇 상태 / 현재 위치</h2>
      <ConnectionStatus wsConnected={wsConnected} bridgeConnected={bridgeConnected} robotState={robotState} />
      <p className="tp-session-state">
        조그 세션:{" "}
        <Pill variant={enabled ? "ok" : "neutral"}>
          {enabled ? `활성 (소유자: ${owner ?? "-"})` : "비활성"}
        </Pill>
      </p>
      {currentPose ? <pre className="tp-pose">{formatPose(currentPose)}</pre> : <p>현재 위치 정보 없음</p>}
      {error && (
        <div className="tp-error">
          <span>{error.message}</span>
          <Button onClick={onAcknowledgeError}>확인</Button>
        </div>
      )}
    </section>
  );
}
