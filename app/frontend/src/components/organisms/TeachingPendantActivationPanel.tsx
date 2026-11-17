import { useState } from "react";
import { Checkbox } from "../atoms/Checkbox";
import { TeachingPendantSafetyModal } from "./TeachingPendantSafetyModal";

interface TeachingPendantActivationPanelProps {
  enabled: boolean;
  owner: string | null;
  error: string | null;
  onEnable: () => Promise<boolean>;
  onDisable: () => void;
}

/** 활성화/비활성화 스위치 + 안전 확인 모달(TP-01, PRD 2장 2단계). 활성화는 반드시
 * 모달 확인을 거치고, 서버가 거부하면(예: 작업 진행 중) 모달에 에러를 보여주며 열린
 * 채로 남긴다. 비활성화는 확인 없이 즉시 요청한다. */
export function TeachingPendantActivationPanel({
  enabled,
  owner,
  error,
  onEnable,
  onDisable,
}: TeachingPendantActivationPanelProps) {
  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleToggle = (checked: boolean) => {
    if (checked) {
      setModalOpen(true);
    } else {
      onDisable();
    }
  };

  const handleConfirm = async () => {
    if (submitting) return;
    setSubmitting(true);
    try {
      const ok = await onEnable();
      if (ok) setModalOpen(false);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="panel tp-activation-panel">
      <h2>조그 세션</h2>
      <Checkbox label={enabled ? "활성화됨" : "비활성화"} checked={enabled} onChange={handleToggle} />
      {enabled && <p className="tp-owner">소유자: {owner ?? "알 수 없음"}</p>}
      <TeachingPendantSafetyModal
        open={modalOpen}
        submitting={submitting}
        error={error}
        onCancel={() => setModalOpen(false)}
        onConfirm={handleConfirm}
      />
    </section>
  );
}
