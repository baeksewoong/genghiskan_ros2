import { Button } from "../atoms/Button";
import type { ReceivePosFullAlert } from "../../hooks/useLiveState";

interface ReceivePosFullModalProps {
  alert: ReceivePosFullAlert | null;
  onClose: () => void;
}

/** success_unload1 후 수령대(1, 2번)가 모두 차 있어 unload2가 대기 중일 때 뜨는 모달.
 * 수령대에서 "수령하기"로 자리가 나면 서버가 자동으로 unload2를 보내고 이 모달도
 * 자동으로 닫힌다(alert.receive_pos_full_cleared). "확인"은 모달만 닫는다. */
export function ReceivePosFullModal({ alert, onClose }: ReceivePosFullModalProps) {
  if (!alert) return null;

  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h3>수령대가 가득 찼습니다 (작업 #{alert.work_id})</h3>
        <p>수령대의 완성품을 수령해 주세요. 자리가 나면 자동으로 이어서 진행됩니다.</p>
        <Button className="btn-primary" onClick={onClose}>
          확인
        </Button>
      </div>
    </div>
  );
}
