import { useState } from "react";
import { Button } from "../atoms/Button";
import { OrderModal } from "./OrderModal";
import type { Shape } from "../../types";

interface OrderFormProps {
  onOrder: (customerName: string, shape: Shape) => Promise<boolean>;
  error: string | null;
}

export function OrderForm({ onOrder, error }: OrderFormProps) {
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (customerName: string, shape: Shape) => {
    if (submitting) return; // 응답 오기 전 중복 클릭 시 주문이 2번 들어가는 것을 막는다.
    setSubmitting(true);
    try {
      const success = await onOrder(customerName, shape);
      if (success) setOpen(false);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="panel order-form">
      <h2>작업요청</h2>
      <Button onClick={() => setOpen(true)}>작업요청</Button>
      <OrderModal
        open={open}
        error={error}
        submitting={submitting}
        onClose={() => setOpen(false)}
        onSubmit={handleSubmit}
      />
    </section>
  );
}
