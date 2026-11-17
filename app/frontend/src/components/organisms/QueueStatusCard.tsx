import { Pill } from "../atoms/Pill";
import type { SqsQueueStatus } from "../../types";

interface QueueStatusCardProps {
  title: string;
  status: SqsQueueStatus | null;
}

/** 단일 SQS 큐(발행/수신)의 상태 카드 — 설정 여부, 조회 실패, 큐 깊이(대기/처리중/지연)를
 * 보여준다. */
export function QueueStatusCard({ title, status }: QueueStatusCardProps) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {!status ? (
        <p>불러오는 중...</p>
      ) : !status.configured ? (
        <Pill variant="bad">큐 미설정</Pill>
      ) : status.error ? (
        <Pill variant="bad">조회 실패: {status.error}</Pill>
      ) : (
        <div className="sqs-counts">
          <div>
            <span className="sqs-count-value">{status.visible}</span>
            <span className="sqs-count-label">대기중</span>
          </div>
          <div>
            <span className="sqs-count-value">{status.in_flight}</span>
            <span className="sqs-count-label">처리중(invisible)</span>
          </div>
          <div>
            <span className="sqs-count-value">{status.delayed}</span>
            <span className="sqs-count-label">지연</span>
          </div>
        </div>
      )}
    </section>
  );
}
