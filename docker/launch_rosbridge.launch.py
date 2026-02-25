#!/usr/bin/env python3

"""
Minimal rosbridge launch — rosbridge WebSocket + rosapi only.
No simulation. Generic bridge for any robot or physical hardware.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    port_arg = DeclareLaunchArgument(
        "port", default_value="9090", description="Port for rosbridge websocket server"
    )

    rosbridge_node = Node(
        package="rosbridge_server",
        executable="rosbridge_websocket",
        name="rosbridge_websocket",
        output="screen",
        parameters=[
            {
                "port": LaunchConfiguration("port"),
                "address": "0.0.0.0",
                "use_compression": False,
                "max_message_size": 10000000,
                "send_action_goals_in_new_thread": True,
                "call_services_in_new_thread": True,
                "default_call_service_timeout": 5.0,
            }
        ],
    )

    rosapi_node = Node(
        package="rosapi",
        executable="rosapi_node",
        name="rosapi",
        output="screen",
    )

    return LaunchDescription([port_arg, rosbridge_node, rosapi_node])
