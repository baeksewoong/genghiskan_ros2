from setuptools import find_packages, setup

package_name = 'sfarm_joint_streamer'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch',
            ['launch/joint_streamer.launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='rokey',
    maintainer_email='ysn08172@gmail.com',
    description=(
        '로봇 팔 조인트 상태(/joint_states)를 백엔드 WebSocket으로 '
        '스트리밍하는 노드 (티칭팬던트 3D 뷰어용)'
    ),
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'joint_streamer = sfarm_joint_streamer.joint_streamer_node:main',
        ],
    },
)
