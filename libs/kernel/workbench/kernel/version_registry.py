"""K3: 版本注册表"""

from pathlib import Path


class VersionRegistry:
    def __init__(self, registry_file: Path):
        self.registry_file = registry_file
        self.versions = {}

    def register_schema(self, name: str, version: str, content):
        if name not in self.versions:
            self.versions[name] = {}
        self.versions[name][version] = content
