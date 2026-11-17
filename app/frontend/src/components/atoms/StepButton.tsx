import type { ButtonHTMLAttributes, ReactNode } from "react";

interface StepButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  pending?: boolean;
  pendingLabel?: ReactNode;
}

/** 조그/그리퍼 패드에서 쓰는 범용 "클릭 1회 = 동작 1회" 버튼. pending이면 로딩 표시를
 * 보여주고 같이 비활성화된다(8.2 스텝 상호 배제 — 이전 응답 전 재클릭 무시). 도메인
 * 타입은 전혀 모른다. */
export function StepButton({
  pending = false,
  pendingLabel = "...",
  disabled,
  className = "",
  children,
  ...props
}: StepButtonProps) {
  return (
    <button
      type="button"
      className={`step-button${className ? ` ${className}` : ""}`}
      disabled={disabled || pending}
      {...props}
    >
      {pending ? pendingLabel : children}
    </button>
  );
}
