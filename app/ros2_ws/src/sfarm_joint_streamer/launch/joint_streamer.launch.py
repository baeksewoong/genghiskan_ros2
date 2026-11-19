"""sfarm_joint_streamer 노드 launch 파일.

사용 예:
  ros2 launch sfarm_joint_streamer joint_streamer.launch.py
  ros2 launch sfarm_joint_streamer joint_streamer.launch.py \
    backend_ws_url:=ws://localhost:8000/ws/robot-state \
    ws_token:=<TOKEN> \
    publish_rate_hz:=20.0 \
    joint_name_prefix:=dsr01_
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    robot_id_arg = DeclareLaunchArgument('robot_id', default_value='robot-arm-1')
    joint_states_topic_arg = DeclareLaunchArgument(
        'joint_states_topic', default_value='/joint_states'
    )
    publish_rate_hz_arg = DeclareLaunchArgument('publish_rate_hz', default_value='10.0')
    backend_ws_url_arg = DeclareLaunchArgument(
        'backend_ws_url', default_value='ws://localhost:8000/ws/robot-state'
    )
    ws_token_arg = DeclareLaunchArgument('ws_token', default_value='')
    joint_name_prefix_arg = DeclareLaunchArgument('joint_name_prefix', default_value='')
    joint_name_overrides_arg = DeclareLaunchArgument(
        'joint_name_overrides', default_value=''
    )
    ws_connect_timeout_sec_arg = DeclareLaunchArgument(
        'ws_connect_timeout_sec', default_value='5.0'
    )
    ws_reconnect_min_sec_arg = DeclareLaunchArgument(
        'ws_reconnect_min_sec', default_value='1.0'
    )
    ws_reconnect_max_sec_arg = DeclareLaunchArgument(
        'ws_reconnect_max_sec', default_value='30.0'
    )

    node = Node(
        package='sfarm_joint_streamer',
        executable='joint_streamer',
        name='sfarm_joint_streamer_node',
        output='screen',
        parameters=[{
            'robot_id': LaunchConfiguration('robot_id'),
            'joint_states_topic': LaunchConfiguration('joint_states_topic'),
            'publish_rate_hz': LaunchConfiguration('publish_rate_hz'),
            'backend_ws_url': LaunchConfiguration('backend_ws_url'),
            'ws_token': LaunchConfiguration('ws_token'),
            'joint_name_prefix': LaunchConfiguration('joint_name_prefix'),
            'joint_name_overrides': LaunchConfiguration('joint_name_overrides'),
            'ws_connect_timeout_sec': LaunchConfiguration('ws_connect_timeout_sec'),
            'ws_reconnect_min_sec': LaunchConfiguration('ws_reconnect_min_sec'),
            'ws_reconnect_max_sec': LaunchConfiguration('ws_reconnect_max_sec'),
        }],
    )

    return LaunchDescription([
        robot_id_arg,
        joint_states_topic_arg,
        publish_rate_hz_arg,
        backend_ws_url_arg,
        ws_token_arg,
        joint_name_prefix_arg,
        joint_name_overrides_arg,
        ws_connect_timeout_sec_arg,
        ws_reconnect_min_sec_arg,
        ws_reconnect_max_sec_arg,
        node,
    ])
