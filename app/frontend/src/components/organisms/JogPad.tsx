import { JogAxisControl } from "../molecules/JogAxisControl";
import type { JogAxis } from "../../types";

interface JogPadProps {
  axes: JogAxis[];
  disabled: boolean;
  pending: boolean;
  onJog: (axis: JogAxis, direction: 1 | -1) => void;
}

/** 방향키 조그 패드 — Cartesian(X/Y/Z/Rx/Ry/Rz 6축) 또는 Joint(J1~J6 6축) 축 목록을
 * page에서 전달받아 렌더링만 한다(PRD 2·4장). 비활성화 세션/연결 끊김/스텝 진행 중에는
 * disabled로 전체를 막는다(8.2, 10번 요구사항). */
export function JogPad({ axes, disabled, pending, onJog }: JogPadProps) {
  return (
    <section className="panel tp-jog-pad-panel">
      <h2>조그 패드</h2>
      <div className="jog-pad">
        {axes.map((axis) => (
          <JogAxisControl
            key={axis}
            axisLabel={axis}
            disabled={disabled}
            pending={pending}
            onJog={(direction) => onJog(axis, direction)}
          />
        ))}
      </div>
    </section>
  );
}
