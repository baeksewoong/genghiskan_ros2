from app.core.runtime import runtime
from app.schemas import SimulatorSettingsOut, SimulatorSettingsPatch


class SimulatorService:
    """print/pickup 타이머 배속(time_scale) 설정. 45초 간격 자동 주문 생성 기능은
    제거됐다 — 더 이상 주문은 자동으로 만들어지지 않는다."""

    @staticmethod
    def get_settings() -> SimulatorSettingsOut:
        return SimulatorSettingsOut(time_scale=runtime.simulator_time_scale)

    @staticmethod
    def patch_settings(patch: SimulatorSettingsPatch) -> SimulatorSettingsOut:
        if patch.time_scale is not None:
            runtime.simulator_time_scale = patch.time_scale
        return SimulatorService.get_settings()
