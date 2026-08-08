"""K8: ROS 2 Lifecycle 状态机"""

from enum import Enum


class LifecycleState(Enum):
    CREATED = "created"
    CONFIGURED = "configured"
    ACTIVE = "active"
    DEACTIVATED = "deactivated"
    FINALIZED = "finalized"


class LifecycleNode:
    def __init__(self, node_name: str):
        self.node_name = node_name
        self.state = LifecycleState.CREATED

    def configure(self):
        if self.state == LifecycleState.CREATED:
            self.state = LifecycleState.CONFIGURED
            return True
        return False

    def activate(self):
        if self.state == LifecycleState.CONFIGURED:
            self.state = LifecycleState.ACTIVE
            return True
        return False

    def get_state(self):
        return self.state


class LifecycleManager:
    def __init__(self):
        self.nodes = {}

    def create_node(self, node_name):
        node = LifecycleNode(node_name)
        self.nodes[node_name] = node
        return node

    def startup_sequence(self):
        for node in self.nodes.values():
            if not node.configure():
                return False
            if not node.activate():
                return False
        return True

    def get_all_states(self):
        return {name: node.get_state().value for name, node in self.nodes.items()}
