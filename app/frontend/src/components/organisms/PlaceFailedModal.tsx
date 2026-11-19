import { Button } from "../atoms/Button";
import type { PlaceFailedAlert } from "../../hooks/useLiveState";

interface PlaceFailedModalProps {
  alert: PlaceFailedAlert | null;
  onYes: (workId: number) => void;
  onNo: () => void;
}

/** robot-events의 프린터 배치 실패 이벤트({"work_id":1,"type":"fail_load2"}) 수신 시
 * 뜨는 모달. 사람이 작업대를 눈으로 확인해 "네"를 누르면 같은 work_id로 로봇 대신
 * success_load2를 robot-events에 주입하고, "아니오"면 관리자 문의 모달로 넘어간다. */
export function PlaceFailedModal({ alert, onYes, onNo }: PlaceFailedModalProps) {
  if (!alert) return null;

  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h3>프린터 배치 실패 (작업 #{alert.work_id})</h3>
        <p>작업대에 잘 들어갔나요?</p>
        <div className="modal-footer">
          <Button onClick={onNo}>아니오</Button>
          <Button className="btn-primary" onClick={() => onYes(alert.work_id)}>
            네
          </Button>
        </div>
      </div>
    </div>
  );
}
