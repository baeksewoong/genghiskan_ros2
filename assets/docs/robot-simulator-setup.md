# 🟡 RG2 그리퍼 포함 두산 협동로봇 Simulator 설치

로봇 구동(실제/가상) 전에 필요한 ROS 2 워크스페이스, 두산 Emulator, 의존성 패키지 설치 절차입니다.

## 1. 소스코드 다운로드

GitHub에서 워크스페이스 소스를 내려받습니다.

```bash
mkdir -p ~/ws_cobot_pjt/ws_dsr
cd ~/ws_cobot_pjt/ws_dsr
git clone https://github.com/ahnisinc/cobot_rg2.git src
# src 폴더에 관련 패키지들이 설치되어 있는지 확인합니다.
```

## 2. 의존성 패키지 설치

```bash
# package.xml 의존성 자동 설치
cd ~/ws_cobot_pjt/ws_dsr
rosdep install -r --from-paths src --ignore-src --rosdistro $ROS_DISTRO -y
```

### 2-1. rosdep이 설치되어 있지 않은 경우 (최초 설치)

```bash
sudo apt update
sudo apt install python3-rosdep

sudo rosdep init
rosdep update
```

설치 확인:

```bash
rosdep --version
```

### 2-2. Doosan Emulator가 설치되어 있지 않은 경우

```bash
# Docker Engine이 설치되어 있지 않다면 먼저 설치: https://docs.docker.com/engine/install/ubuntu/

# 현재 사용자를 docker 그룹에 추가 (launch에서 docker run 호출 시 필수)
sudo usermod -aG docker $USER
newgrp docker
```

```bash
cd ~/ws_cobot_pjt/ws_dsr/src/doosan-robot2
chmod +x ./install_emulator.sh
sudo ./install_emulator.sh
```

## 3. 빌드

```bash
cd ~/ws_cobot_pjt/ws_dsr
colcon build
source install/setup.bash
```

`.bashrc`에 아래 항목을 추가합니다 (이미 있다면 추가하지 않습니다).

```bash
export PYTHONPATH=$PYTHONPATH:~/ws_cobot_pjt/ws_dsr/install/dsr_common2/lib/dsr_common2/imp
```

## 4. 실행 환경 설정

```bash
source ~/ws_cobot_pjt/ws_dsr/install/setup.bash
```

### Virtual 모드 (시뮬레이션)

```bash
# 브링업 (두산로봇 M0609 + 그리퍼)
ros2 launch m0609_rg2_bringup bringup.launch.py port:=12345

# 또는 아래 명령어, 위와 동일한 동작
ros2 launch m0609_rg2_bringup bringup.launch.py mode:=virtual host:=127.0.0.1 port:=12345 model:=m0609
```

### Real 모드 (실제 로봇)

```bash
# 브링업 (두산로봇 M0609 + 그리퍼)
ros2 launch m0609_rg2_bringup bringup.launch.py mode:=real host:=192.168.1.100 port:=12345 model:=m0609
```
