"""ros2-wsl-doctor: find out why a ROS 2 topic publishes and nothing arrives.

The fault class this covers: the node is up, the topic exists, and no
subscriber ever receives a byte. On FastDDS under WSL2 (and plain Linux) the
causes are usually environmental and every one of them looks like broken
hardware or a dead driver from the outside.
"""
from .report import Finding, Status, render_table  # noqa: F401

__version__ = "0.1.0"
