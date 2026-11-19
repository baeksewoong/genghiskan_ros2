import { Button } from "../atoms/Button";

interface AdminContactModalProps {
  open: boolean;
  onClose: () => void;
}

/** 프린터 배치 실패 알럿에서 "아니오"를 눌렀을 때 뜨는 모달. 닫기 버튼만 있고,
 * 그 외엔 아무 상태도 바꾸지 않는다 — 운영자가 직접 관리자에게 알려야 한다. */
export function AdminContactModal({ open, onClose }: AdminContactModalProps) {
  if (!open) return null;

  return (
    <div className="modal-backdrop">
      <div className="modal">
        <h3>관리자에게 문의</h3>
        <p>작업대 상태를 확인할 수 없습니다. 관리자에게 문의해 주세요.</p>
        <Button onClick={onClose}>닫기</Button>
      </div>
    </div>
  );
}
