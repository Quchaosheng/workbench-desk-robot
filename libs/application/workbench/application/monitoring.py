"""Prometheus metrics"""

import logging

logger = logging.getLogger("Monitoring")


class SystemMetrics:
    """Prometheus-compatible metrics collection"""

    def __init__(self):
        self.counters = {}
        self.gauges = {}
        self.histograms = {}

    def increment_counter(self, name: str, value: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + value

    def set_gauge(self, name: str, value: float) -> None:
        self.gauges[name] = value

    def record_histogram(self, name: str, value: float) -> None:
        if name not in self.histograms:
            self.histograms[name] = []
        self.histograms[name].append(value)

    def export_prometheus(self) -> str:
        lines = []
        for name, value in self.counters.items():
            lines.append(f"{name} {value}")
        for name, value in self.gauges.items():
            lines.append(f"{name} {value}")
        return "\n".join(lines)


system_metrics = SystemMetrics()
