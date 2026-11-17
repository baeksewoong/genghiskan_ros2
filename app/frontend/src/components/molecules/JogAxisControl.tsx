import { StepButton } from "../atoms/StepButton";

interface JogAxisControlProps {
  axisLabel: string;
  disabled: boolean;
  pending: boolean;
  onJog: (direction: 1 | -1) => void;
}

/** 조그 패드에서 축 하나(+/- 쌍)를 표현하는 molecule. Cartesian 축("X"/"RZ" 등)인지
 * Joint 축("J1" 등)인지는 모르고, page/organism이 결정한 라벨 문자열만 받는다. */
export function JogAxisControl({ axisLabel, disabled, pending, onJog }: JogAxisControlProps) {
  return (
    <div className="jog-axis-control">
      <span className="jog-axis-label">{axisLabel}</span>
      <div className="jog-axis-buttons">
        <StepButton disabled={disabled} pending={pending} onClick={() => onJog(-1)} aria-label={`${axisLabel} -`}>
          −
        </StepButton>
        <StepButton disabled={disabled} pending={pending} onClick={() => onJog(1)} aria-label={`${axisLabel} +`}>
          +
        </StepButton>
      </div>
    </div>
  );
}
