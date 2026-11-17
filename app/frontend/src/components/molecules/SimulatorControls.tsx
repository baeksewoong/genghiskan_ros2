import { NumberField } from "../atoms/NumberField";
import type { SimulatorSettings } from "../../types";

interface SimulatorControlsProps {
  settings: SimulatorSettings;
  onPatch: (patch: Partial<SimulatorSettings>) => void;
}

export function SimulatorControls({ settings, onPatch }: SimulatorControlsProps) {
  return (
    <div className="simulator-controls">
      <NumberField
        label="배율"
        min={0.1}
        step={0.1}
        value={settings.time_scale}
        onChange={(time_scale) => onPatch({ time_scale })}
      />
    </div>
  );
}
