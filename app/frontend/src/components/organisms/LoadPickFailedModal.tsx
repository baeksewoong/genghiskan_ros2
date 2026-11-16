import { Button } from "../atoms/Button";
import type { LoadPickFailedAlert } from "../../hooks/useLiveState";

interface LoadPickFailedModalProps {
  alert: LoadPickFailedAlert | null;
  onConfirm: (workId: number) => void;
}

/** robot-events의 베드 집기 실패 이벤트(예: {"work_id":1,"type":"fail_load1"}) 수신 시
 * 뜨는 모달. 사람이 적재대의 bed 위치를 바로잡은 뒤 "확인"을 누르면 같은 work_id로
 * LOAD 명령을 SQS에 재전송한다. */
export function LoadPickFailedModal({ alert, onConfirm }: LoadPickFailedModalProps) {
  if (!alert) return null;

  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h3>베드 집기 실패</h3>
        <p>적재대의 베드를 확인해 주세요.</p>
        <Button className="btn-primary" onClick={() => onConfirm(alert.work_id)}>
          확인
        </Button>
      </div>
    </div>
  );
}
