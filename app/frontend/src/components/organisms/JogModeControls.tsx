import type { JogRefFrame, JogSpace } from "../../types";

// 9장 비기능요구사항 상한: Cartesian 선형 ≤20mm, 회전/Joint ≤15deg.
const LINEAR_PRESETS_MM = [1, 5, 10, 20];
const ROTATIONAL_PRESETS_DEG = [1, 5, 10, 15];
const JOINT_PRESETS_DEG = [1, 5, 10, 15];

interface JogModeControlsProps {
  mode: JogSpace;
  refFrame: JogRefFrame;
  stepLinearMm: number;
  stepRotationalDeg: number;
  stepJointDeg: number;
  disabled: boolean;
  onChangeMode: (mode: JogSpace) => void;
  onChangeRefFrame: (refFrame: JogRefFrame) => void;
  onChangeStepLinearMm: (mm: number) => void;
  onChangeStepRotationalDeg: (deg: number) => void;
  onChangeStepJointDeg: (deg: number) => void;
}

/** 기준 좌표계(Base/Tool, Cartesian일 때만 의미 있음) + 모드(Cartesian/Joint) + 스텝
 * 크기 선택(TP-03~05). 완전히 controlled — 선택값은 모두 page 상태다. */
export function JogModeControls({
  mode,
  refFrame,
  stepLinearMm,
  stepRotationalDeg,
  stepJointDeg,
  disabled,
  onChangeMode,
  onChangeRefFrame,
  onChangeStepLinearMm,
  onChangeStepRotationalDeg,
  onChangeStepJointDeg,
}: JogModeControlsProps) {
  return (
    <section className="panel tp-mode-controls">
      <h2>조그 설정</h2>

      <div className="tp-field">
        <span className="tp-field-label">모드</span>
        <div className="tp-toggle-row">
          <button
            type="button"
            className={`tp-toggle${mode === "TASK" ? " selected" : ""}`}
            disabled={disabled}
            onClick={() => onChangeMode("TASK")}
          >
            Cartesian
          </button>
          <button
            type="button"
            className={`tp-toggle${mode === "JOINT" ? " selected" : ""}`}
            disabled={disabled}
            onClick={() => onChangeMode("JOINT")}
          >
            Joint
          </button>
        </div>
      </div>

      {mode === "TASK" && (
        <div className="tp-field">
          <span className="tp-field-label">기준 좌표계</span>
          <div className="tp-toggle-row">
            <button
              type="button"
              className={`tp-toggle${refFrame === "BASE" ? " selected" : ""}`}
              disabled={disabled}
              onClick={() => onChangeRefFrame("BASE")}
            >
              Base
            </button>
            <button
              type="button"
              className={`tp-toggle${refFrame === "TOOL" ? " selected" : ""}`}
              disabled={disabled}
              onClick={() => onChangeRefFrame("TOOL")}
            >
              Tool
            </button>
          </div>
        </div>
      )}

      {mode === "TASK" ? (
        <>
          <div className="tp-field">
            <span className="tp-field-label">선형 스텝 (mm)</span>
            <div className="tp-toggle-row">
              {LINEAR_PRESETS_MM.map((mm) => (
                <button
                  key={mm}
                  type="button"
                  className={`tp-toggle${stepLinearMm === mm ? " selected" : ""}`}
                  disabled={disabled}
                  onClick={() => onChangeStepLinearMm(mm)}
                >
                  {mm}mm
                </button>
              ))}
            </div>
          </div>
          <div className="tp-field">
            <span className="tp-field-label">회전 스텝 (deg)</span>
            <div className="tp-toggle-row">
              {ROTATIONAL_PRESETS_DEG.map((deg) => (
                <button
                  key={deg}
                  type="button"
                  className={`tp-toggle${stepRotationalDeg === deg ? " selected" : ""}`}
                  disabled={disabled}
                  onClick={() => onChangeStepRotationalDeg(deg)}
                >
                  {deg}°
                </button>
              ))}
            </div>
          </div>
        </>
      ) : (
        <div className="tp-field">
          <span className="tp-field-label">Joint 스텝 (deg)</span>
          <div className="tp-toggle-row">
            {JOINT_PRESETS_DEG.map((deg) => (
              <button
                key={deg}
                type="button"
                className={`tp-toggle${stepJointDeg === deg ? " selected" : ""}`}
                disabled={disabled}
                onClick={() => onChangeStepJointDeg(deg)}
              >
                {deg}°
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
