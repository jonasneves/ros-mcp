#!/bin/bash
set -e

source /opt/ros/jazzy/setup.bash
export USER=${USER:-root}
if [ -f /ros2_ws/install/setup.bash ]; then
  source /ros2_ws/install/setup.bash
fi

rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true
export LIBGL_ALWAYS_SOFTWARE=1
Xvfb :99 -screen 0 1280x800x24 -ac +extension GLX +render -noreset 2>/dev/null &

# Wait for Xvfb socket instead of sleeping
until [ -e /tmp/.X11-unix/X99 ]; do sleep 0.1; done
export DISPLAY=:99

x11vnc -display :99 -nopw -forever -shared -rfbport 5900 -quiet -nodpms &
websockify --web=/usr/share/novnc "${NOVNC_PORT:-8080}" localhost:5900 &

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file:///cyclonedds.xml

exec "$@"
