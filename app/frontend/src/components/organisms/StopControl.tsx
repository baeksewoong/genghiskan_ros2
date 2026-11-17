import { Button } from "../atoms/Button";

interface StopControlProps {
  disabled: boolean;
  stopping: boolean;
  onStop: () => void;
}

/** 정지 요청(TP-09). 8.4의 한계 — SQS 왕복 특성상 이미 발행/수신된 스텝 자체를
 * 중간에 멈추는 것은 보장되지 않는다 — 를 문구로 그대로 알린다. */
export function StopControl({ disabled, stopping, onStop }: StopControlProps) {
  return (
    <section className="panel tp-stop-panel">
      <h2>정지</h2>
      <Button className="tp-stop-button" onClick={onStop} disabled={disabled || stopping}>
        {stopping ? "정지 요청 중..." : "정지"}
      </Button>
      <p className="tp-stop-note">정지 요청 중 — 이미 시작된 이동은 완료될 수 있음</p>
    </section>
  );
}
