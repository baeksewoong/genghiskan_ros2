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
    <section className="order-hero">
      <span className="order-hero-icon" aria-hidden="true">
        ✨
      </span>
      <div className="order-hero-text">
        <h2 className="order-hero-title">나만의 3D 프린트 작업요청</h2>
        <p className="order-hero-sub">원하는 모양을 고르고 터치 한 번으로 작업을 시작하세요</p>
      </div>
      <Button className="order-hero-button" onClick={() => setOpen(true)}>
        🖨️&nbsp;&nbsp;작업요청 시작하기
      </Button>
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
