import { Button } from "../atoms/Button";

interface TeachingPendantSafetyModalProps {
  open: boolean;
  submitting: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}

/** 조그 세션 활성화 전 안전 확인 모달(PRD 2장 2단계). "확인" 전까지는 활성화 요청을
 * 보내지 않는다. */
export function TeachingPendantSafetyModal({
  open,
  submitting,
  error,
  onCancel,
  onConfirm,
}: TeachingPendantSafetyModalProps) {
  if (!open) return null;

  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h3>실물 로봇 조그 활성화</h3>
        <p>실물 로봇이 움직입니다. 주변에 사람이나 장애물이 없는지 확인하세요.</p>
        {error && <p className="error">{error}</p>}
        <div className="modal-footer">
          <Button onClick={onCancel} disabled={submitting}>
            취소
          </Button>
          <Button onClick={onConfirm} disabled={submitting}>
            {submitting ? "활성화 중..." : "확인했습니다 — 활성화"}
          </Button>
        </div>
      </div>
    </div>
  );
}
