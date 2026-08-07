"""Minimal Motion node used for the phase-0 empty-world self test.

It does nothing but come up, log a unified start line carrying a ``run_id``,
append a startup ExecutionEvent to a (fake) EvidenceSink, then either run a
bounded self test and exit cleanly (default) or spin indefinitely. It exists so
the package's launch can be exercised without any external bringup (no Gazebo,
no arm, no MCU). Real adapter behaviour lands in later phases.

Behaviour is controlled by the ``self_test_seconds`` ROS parameter:
- ``> 0`` (default 2.0): spin for that long, log "self-test passed", exit 0.
  This is the CI-friendly path — no SIGINT needed, launch sees a clean exit.
- ``<= 0``: spin indefinitely (interactive use; stop with Ctrl-C).

``rclpy`` is an apt/rosdep-managed ROS 2 runtime dependency, not a uv-managed
one. The import is done lazily inside ``main`` so the pure-Python parts of this
package (evidence, logging_setup and their tests) import and run under a plain
uv environment where rclpy is not present.
"""

from __future__ import annotations

import logging
import time
import uuid

from .evidence import ExecutionEvent, FakeEvidenceSink
from .logging_setup import configure_logging, get_action_logger


def main(args: list[str] | None = None) -> None:
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node

    configure_logging(logging.INFO)
    run_id = uuid.uuid4().hex[:12]

    class ScaffoldNode(Node):
        def __init__(self) -> None:
            super().__init__("workbench_motion_scaffold")
            self.log = get_action_logger("workbench_motion.scaffold", run_id=run_id)
            self.self_test_seconds = self.declare_parameter("self_test_seconds", 2.0).get_parameter_value().double_value
            # Phase-0 sink is the test double; production sink is wired in later
            # phases via the World Model Event Store adapter.
            self._sink = FakeEvidenceSink()
            ref = self._sink.append(ExecutionEvent(event_type="node_started", run_id=run_id, action_id="-"))
            self.log.info("workbench_motion scaffold node up; startup event ref=%s", ref)

    rclpy.init(args=args)
    node = ScaffoldNode()
    try:
        if node.self_test_seconds > 0:
            deadline = time.monotonic() + node.self_test_seconds
            while rclpy.ok() and time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=0.1)
            node.log.info("self-test passed; shutting down cleanly")
        else:
            rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
