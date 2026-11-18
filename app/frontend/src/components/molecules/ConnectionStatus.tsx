import { Pill } from "../atoms/Pill";

interface ConnectionStatusProps {
  wsConnected: boolean;
}

/** 서버 실시간 연결(/ws/client) 상태. 로봇과는 SQS로만 통신하므로 별도 "로봇 연결"
 * 상태는 없다 — 로봇 응답 여부는 조그/그리퍼 완료·실패·타임아웃(TP-11)으로 드러난다. */
export function ConnectionStatus({ wsConnected }: ConnectionStatusProps) {
  return (
    <div className="status-group">
      <Pill variant={wsConnected ? "ok" : "bad"}>서버 {wsConnected ? "연결됨" : "끊김"}</Pill>
    </div>
  );
}
