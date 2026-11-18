import { Button } from "../atoms/Button";
import type { UnloadPickFailedAlert } from "../../hooks/useLiveState";

interface UnloadPickFailedModalProps {
  alert: UnloadPickFailedAlert | null;
  onConfirm: (workId: number) => void;
}

/** robot-events의 완성품 집기 실패 이벤트({"work_id":1,"type":"fail_unload1"}) 수신 시
 * 뜨는 모달. 사람이 작업대의 베드를 확인한 뒤 "확인"을 누르면 같은 work_id로
 * unload1 명령을 SQS에 재전송한다. */
export function UnloadPickFailedModal({ alert, onConfirm }: UnloadPickFailedModalProps) {
  if (!alert) return null;

  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h3>완성품 집기 실패 (작업 #{alert.work_id})</h3>
        <p>작업대에 베드를 확인하세요!</p>
        <Button className="btn-primary" onClick={() => onConfirm(alert.work_id)}>
          확인
        </Button>
      </div>
    </div>
  );
}
