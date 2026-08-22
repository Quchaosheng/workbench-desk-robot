from __future__ import annotations

import re
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

UUID_PATTERN = re.compile(r'(?P<prefix>\(uuid\s+")(?P<value>[0-9a-fA-F-]{36})(?P<suffix>"\))')
BOARD_HEAD_ORDER = {
    "version": 0,
    "generator": 1,
    "generator_version": 2,
    "general": 3,
    "paper": 4,
    "title_block": 5,
    "layers": 6,
    "setup": 7,
    "net": 20,
    "footprint": 30,
    "gr_arc": 40,
    "gr_circle": 41,
    "gr_curve": 42,
    "gr_line": 43,
    "gr_poly": 44,
    "gr_rect": 45,
    "gr_text": 46,
    "gr_text_box": 47,
    "segment": 60,
    "arc": 61,
    "via": 62,
    "zone": 70,
    "dimension": 80,
    "group": 90,
}


class DeterministicUuidFactory:
    def __init__(self, artifact_key: str):
        self.artifact_key = artifact_key
        self.reset()

    def reset(self) -> None:
        self._next_index = 0

    def next(self) -> str:
        value = uuid5(NAMESPACE_URL, f"workbench-desk-robot/{self.artifact_key}/{self._next_index}")
        self._next_index += 1
        return str(value)


def normalize_kicad_uuid_text(text: str, artifact_key: str) -> tuple[str, int]:
    replacements: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        original = match.group("value").lower()
        if original not in replacements:
            index = len(replacements)
            replacements[original] = str(uuid5(NAMESPACE_URL, f"workbench-desk-robot/{artifact_key}/{index}"))
        return f"{match.group('prefix')}{replacements[original]}{match.group('suffix')}"

    return UUID_PATTERN.sub(replace, text), len(replacements)


def _matching_paren(text: str, opening: int) -> int:
    depth = 0
    quoted = False
    escaped = False
    for index in range(opening, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if quoted and char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    raise ValueError("unbalanced KiCad S-expression")


def _list_head(block: str) -> str:
    match = re.match(r"\(\s*([^\s()]+)", block)
    if not match:
        raise ValueError("KiCad child expression has no list head")
    return match.group(1)


def _semantic_sort_key(head: str, block: str) -> str:
    without_uuid = UUID_PATTERN.sub("", block)
    if head == "footprint":
        reference = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', without_uuid)
        if reference:
            return reference.group(1)
    if head == "net":
        net = re.match(r'\(net\s+(\d+)\s+"([^"]+)"', without_uuid)
        if net:
            return f"{int(net.group(1)):06d}:{net.group(2)}"
    return " ".join(without_uuid.split())


def canonicalize_kicad_board_text(text: str) -> str:
    text = text.replace("\r\n", "\n")
    opening = text.find("(kicad_pcb")
    if opening < 0:
        raise ValueError("file is not a kicad_pcb expression")
    root_end = _matching_paren(text, opening)
    if text[root_end:].strip():
        raise ValueError("unexpected data follows kicad_pcb expression")
    body_start = opening + len("(kicad_pcb")
    position = body_start
    children: list[tuple[int, str, str]] = []
    while position < root_end - 1:
        while position < root_end - 1 and text[position].isspace():
            position += 1
        if position >= root_end - 1:
            break
        if text[position] != "(":
            raise ValueError("unexpected atom in kicad_pcb body")
        end = _matching_paren(text, position)
        block = text[position:end]
        children.append((len(children), _list_head(block), block))
        position = end
    singleton_heads = {
        "version",
        "generator",
        "generator_version",
        "general",
        "paper",
        "title_block",
        "layers",
        "setup",
    }
    children.sort(
        key=lambda item: (
            BOARD_HEAD_ORDER.get(item[1], 100),
            f"{item[0]:08d}" if item[1] in singleton_heads else _semantic_sort_key(item[1], item[2]),
        )
    )
    newline = "\n"
    prefix = text[:body_start].rstrip()
    suffix = text[root_end - 1 :]
    return prefix + newline + newline.join(f"\t{block}" for _, _, block in children) + newline + suffix


def normalize_kicad_uuids(path: Path, artifact_key: str) -> int:
    original = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    normalized, uuid_count = normalize_kicad_uuid_text(original, artifact_key)
    encoded = normalized.encode("utf-8")
    if encoded != path.read_bytes():
        path.write_bytes(encoded)
    return uuid_count


def normalize_kicad_board(path: Path, artifact_key: str) -> int:
    original = path.read_text(encoding="utf-8")
    canonical = canonicalize_kicad_board_text(original)
    normalized, uuid_count = normalize_kicad_uuid_text(canonical, artifact_key)
    encoded = normalized.encode("utf-8")
    if encoded != path.read_bytes():
        path.write_bytes(encoded)
    return uuid_count


def normalize_line_endings(path: Path) -> None:
    original = path.read_bytes()
    normalized = original.replace(b"\r\n", b"\n")
    if normalized != original:
        path.write_bytes(normalized)
