from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# pydantic-settings의 env_file 로딩은 .env 값을 Settings 필드에만 채워주고
# os.environ 자체는 바꾸지 않는다. boto3는 AWS_ACCESS_KEY_ID 등 자격증명을
# os.environ에서 직접 찾으므로(Settings에 선언하지 않은 키), SQS를 쓰려면
# .env를 실제 프로세스 환경변수로도 로드해 둬야 한다.
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "mysql+aiomysql://printshop:printshop@localhost:3306/printshop"
    cors_origins: str = "http://localhost:5173"

    timer_sweep_interval_sec: float = 0.5

    # 작업요청(SQS) 경로 전용 (PRD: assets/docs/prd-work-request-sqs.md 7장).
    # 기본값은 빈 문자열 — 설정하지 않으면 produce/consume 모두 조용히 비활성화된다.
    # (ROS 2 쪽 sfarm_bridge.py처럼 실제 AWS 큐 URL을 코드에 기본값으로 박아두지 않기 위함.)
    aws_region: str = "ap-northeast-2"
    command_queue_url: str = ""
    event_queue_url: str = ""
    sqs_poll_wait_sec: int = 20

    # 실물 로봇 조인트 각도 실시간 피드(/ws/robot-state, ROS2 → 백엔드) 인증 토큰.
    # 이 엔드포인트는 외부에 노출될 수 있는 "쓰기" 경로이므로 event_queue_url류와
    # 달리 "비어있으면 기능 끔"이 아니라 "비어있으면 거부(fail-closed)"가 기본값이다 —
    # 토큰을 명시적으로 설정하지 않으면 /ws/robot-state는 어떤 연결도 받지 않는다.
    robot_state_ws_token: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
