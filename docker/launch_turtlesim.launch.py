#!/usr/bin/env python3

"""
ROS2 Launch file for Turtlesim.
Reads TURTLESIM_NAMESPACE from the environment so the same file works for
turtlesim1 (ts1), turtlesim2 (ts2), and turtlesim3 (ts3) containers.
Rosbridge is handled by the dedicated rosbridge container.
"""

import os

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    namespace = os.environ.get("TURTLESIM_NAMESPACE", "ts1")

    return LaunchDescription([
        Node(
            package="turtlesim",
            executable="turtlesim_node",
            name="turtlesim",
            namespace=namespace,
            output="screen",
        ),
    ])
