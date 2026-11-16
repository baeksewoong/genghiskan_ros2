from setuptools import find_packages, setup

package_name = 'sfarm_robot'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='hbc',
    maintainer_email='20211270@vision.hoseo.edu',
    description='3Farm Doosan robot action server (/sfarm/insert, /sfarm/eject)',
    license='MIT',
    entry_points={
        'console_scripts': [
            'robot_action_server = sfarm_robot.robot_action_server:main',
            'motion_test = sfarm_robot.motion_test:main',
        ],
    },
)
