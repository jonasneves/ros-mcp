# Tools reference

### Connection
| Tool | Description |
|---|---|
| `connect_to_robot` | Set rosbridge IP/port and verify connectivity |
| `ping_robot` | Ping an IP and check if a port is open |

### Topics
| Tool | Description |
|---|---|
| `get_topics` | List all topics |
| `get_topic_type` | Message type for a topic |
| `get_topic_details` | Publishers, subscribers, type |
| `get_message_details` | Full message type definition |
| `subscribe_once` | Receive the first message on a topic |
| `subscribe_for_duration` | Collect messages for N seconds |
| `publish_once` | Publish a single message |
| `publish_for_durations` | Publish a sequence of timed messages |
| `turn_by_angle` | Rotate a robot by an exact angle (deg) |
| `move_by_distance` | Move a robot a specified distance (m) |
| `move_robots` | Move multiple robots simultaneously |

### Services
| Tool | Description |
|---|---|
| `get_services` | List all services |
| `get_service_type` | Type for a service |
| `get_service_details` | Request/response structure |
| `call_service` | Call a service with a request payload |

### Nodes
| Tool | Description |
|---|---|
| `get_nodes` | List all nodes |
| `get_connected_robots` | Discover robots by finding cmd_vel topics |
| `get_node_details` | Publishers, subscribers, services for a node |

### Actions (ROS 2)
| Tool | Description |
|---|---|
| `get_actions` | List all actions |
| `get_action_details` | Goal/result/feedback structure |
| `send_action_goal` | Send a goal to an action server |
| `get_action_status` | Check action goal status |
| `cancel_action_goal` | Cancel an action goal |

### Parameters (ROS 2)
| Tool | Description |
|---|---|
| `get_parameter` | Get a parameter value |
| `set_parameter` | Set a parameter value |
| `has_parameter` | Check if a parameter exists |
| `delete_parameter` | Delete a parameter |
| `get_parameters` | List all parameters for a node |
| `get_parameter_details` | Value, type, and metadata for a parameter |

### Robot config
| Tool | Description |
|---|---|
| `detect_ros_version` | Detect ROS version and distro |
| `get_verified_robots_list` | List robots with pre-built specs |
| `get_verified_robot_spec` | Load spec and prompts for a verified robot |
| `get_robot_description` | Fetch the robot URDF from `/robot_description` |
| `get_joint_states` | Read joint positions (rad), velocities, and efforts |

### Images
| Tool | Description |
|---|---|
| `analyze_previously_received_image` | Analyze an image received from a topic |
