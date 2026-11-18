from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='sfarm_robot',
            executable='robot_action_server',
            name='sfarm_robot_action_server',
            output='screen',
        ),
        Node(
            package='sfarm_bridge',
            executable='sfarm_bridge',
            name='sfarm_bridge_node',
            output='screen',
        ),
    ])