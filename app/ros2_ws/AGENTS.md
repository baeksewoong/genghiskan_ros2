# ROS 2 Workspace Rules (`app/ros2_ws`)

이 디렉토리(`/home/rokey/workspace/genghiskan_ros2/app/ros2_ws`)는 프로젝트의 **ROS 2 Jazzy 워크스페이스 루트**입니다.

## 필수 개발 수칙

1. **빌드 위치 고정**:
   - `colcon build`는 반드시 이 워크스페이스 루트(`app/ros2_ws`)에서 실행합니다.
   - 표준 빌드 명령어 (레포 루트 기준):
     ```bash
     source .claude/skills/ros2-workspace-ops/scripts/ros2_env.sh
     cd app/ros2_ws
     colcon build --symlink-install
     ```
   - 인터페이스 패키지(`printshop_interfaces` 등 `ament_cmake` 메시지/액션 패키지)를 수정한 경우 해당 패키지를 먼저 빌드하고 `install/setup.bash`를 다시 소싱하세요.

2. **환경 오버레이 체인**:
   - Underlay 1: `/opt/ros/jazzy`
   - Underlay 2 (Doosan Robot2 & OnRobot RG2): `~/ws_cobot_pjt/ws_dsr` (머신마다 경로가 다르면
     `export DSR_WS_PATH=...`로 덮어쓰기 — `ros2_env.sh` 참고)
   - Overlay (현재 워크스페이스): `app/ros2_ws`
   - 기본 도메인: `ROS_DOMAIN_ID=20`

3. **Python 노드 작성 표준 (`rclpy`)**:
   - 블로킹 작업(WebSocket 클라이언트, AWS SQS 폴링, `DSR_ROBOT2` 동기 모션 함수)은 `rclpy.spin()` 메인 콜백을 막지 않도록 별도 데몬 스레드나 `MultiThreadedExecutor` + `ReentrantCallbackGroup`으로 분리합니다.
   - 종료 시 `ExternalShutdownException`과 `KeyboardInterrupt`를 안전하게 처리하고 스레드 이벤트(`threading.Event`)를 정리합니다.
   - 환경변수(`.env`)가 필요한 노드는 실행 위치와 무관하게 로드되도록 패키지 경로 또는 워크스페이스 상위 경로를 탐색하거나 ROS 파라미터(`declare_parameter`)로 주입받도록 작성합니다.

4. **연동 스킬 참조** (레포 루트 `.claude/skills/` 아래, Claude Code가 자동으로 인식):
   - 워크스페이스 빌드/패키지 관리: `../../.claude/skills/ros2-workspace-ops/SKILL.md`
   - 두산 로봇 `DSR_ROBOT2` 제어: `../../.claude/skills/doosan-dsr-control/SKILL.md`
   - 프린트샵 브릿지 & 액션 프로토콜: `../../.claude/skills/printshop-ros2-bridge/SKILL.md`
   - ROS 2 CLI 진단 및 디버깅: `../../.claude/skills/ros2-cli-diagnostics/SKILL.md`
   - ROS 2 작업 전담 에이전트: `../../.claude/agents/ros2-dev.md`
