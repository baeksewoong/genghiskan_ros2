import { useEffect, useState } from "react";
import { WorkHistoryPanel } from "../components/organisms/WorkHistoryPanel";
import { WorkHistoryTemplate } from "../components/templates/WorkHistoryTemplate";
import { api } from "../lib/api";
import { parseServerTime } from "../lib/time";
import type { Order } from "../types";

// 백엔드 limit 상한(app/backend/app/api/routers/orders.py)만큼 가져와 전체 히스토리를 보여준다.
const HISTORY_LIMIT = 500;

export function WorkHistoryPage() {
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    api
      .getOrders({ limit: HISTORY_LIMIT })
      .then((data) => {
        if (cancelled) return;
        // 서버가 이미 created_at 내림차순으로 주지만, 방어적으로 프론트에서도 다시 정렬한다.
        const sorted = [...data].sort(
          (a, b) => parseServerTime(b.created_at) - parseServerTime(a.created_at)
        );
        setOrders(sorted);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <WorkHistoryTemplate
      error={error && <p className="sqs-status-error">작업 히스토리 조회 실패: {error}</p>}
      history={<WorkHistoryPanel orders={orders} />}
    />
  );
}
