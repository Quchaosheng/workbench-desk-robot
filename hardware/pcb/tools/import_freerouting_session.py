from __future__ import annotations

import argparse
import re
from itertools import pairwise
from pathlib import Path

try:
    import pcbnew
except ImportError as exc:
    raise SystemExit("Run with KiCad's bundled Python interpreter (bin/python.exe)") from exc


TOKEN = re.compile(r'\s*(\(|\)|"(?:\\.|[^"\\])*"|[^\s()]+)')
LAYERS = {
    "F.Cu": pcbnew.F_Cu,
    "In1.Cu": pcbnew.In1_Cu,
    "In2.Cu": pcbnew.In2_Cu,
    "In3.Cu": pcbnew.In3_Cu,
    "In4.Cu": pcbnew.In4_Cu,
    "In5.Cu": pcbnew.In5_Cu,
    "In6.Cu": pcbnew.In6_Cu,
    "B.Cu": pcbnew.B_Cu,
}


def via_dimensions(descriptor: object) -> tuple[float, float]:
    match = re.search(r"_(\d+):(\d+)_um", str(descriptor))
    if match:
        return float(match.group(1)) / 1000.0, float(match.group(2)) / 1000.0
    return 0.6, 0.3


def tokenize(text: str) -> list[str]:
    tokens = []
    cursor = 0
    while cursor < len(text):
        match = TOKEN.match(text, cursor)
        if not match:
            if text[cursor:].strip():
                raise ValueError(f"invalid session syntax at byte {cursor}")
            break
        tokens.append(match.group(1))
        cursor = match.end()
    return tokens


def parse_session(text: str) -> list[object]:
    tokens = tokenize(text)
    cursor = 0

    def parse_value() -> object:
        nonlocal cursor
        if cursor >= len(tokens):
            raise ValueError("unexpected end of session")
        token = tokens[cursor]
        cursor += 1
        if token == "(":
            result = []
            while cursor < len(tokens) and tokens[cursor] != ")":
                result.append(parse_value())
            if cursor >= len(tokens):
                raise ValueError("unterminated session list")
            cursor += 1
            return result
        if token == ")":
            raise ValueError("unexpected closing parenthesis")
        if token.startswith('"'):
            return bytes(token[1:-1], "utf-8").decode("unicode_escape")
        return token

    root = parse_value()
    if cursor != len(tokens) or not isinstance(root, list):
        raise ValueError("session must contain one top-level list")
    return root


def child(node: list[object], name: str) -> list[object]:
    for item in node:
        if isinstance(item, list) and item and item[0] == name:
            return item
    raise ValueError(f"session is missing {name}")


def coordinate(value: object, units_per_mm: float):
    return pcbnew.FromMM(float(str(value)) / units_per_mm)


def validate_placement(board, session: list[object]) -> None:
    placement = child(session, "placement")
    resolution = child(placement, "resolution")
    if len(resolution) != 3 or resolution[1] != "um":
        raise ValueError(f"unsupported placement resolution: {resolution}")
    units_per_mm = float(str(resolution[2])) * 1000.0
    expected = {}
    for component in placement[1:]:
        if not isinstance(component, list) or not component or component[0] != "component":
            continue
        for item in component[1:]:
            if not isinstance(item, list) or len(item) < 4 or item[0] != "place":
                continue
            expected[str(item[1])] = (
                float(str(item[2])) / units_per_mm,
                -float(str(item[3])) / units_per_mm,
                float(str(item[5])) if len(item) > 5 else 0.0,
            )

    actual = {footprint.GetReference(): footprint for footprint in board.GetFootprints()}
    missing = sorted(set(expected) - set(actual))
    if missing:
        raise ValueError(f"session placement references missing footprints: {missing}")
    drift = []
    for reference, (expected_x, expected_y, expected_rotation) in expected.items():
        position = actual[reference].GetPosition()
        actual_x = pcbnew.ToMM(position.x)
        actual_y = pcbnew.ToMM(position.y)
        actual_rotation = actual[reference].GetOrientationDegrees()
        rotation_delta = (actual_rotation - expected_rotation + 180.0) % 360.0 - 180.0
        if abs(actual_x - expected_x) > 0.01 or abs(actual_y - expected_y) > 0.01 or abs(rotation_delta) > 0.01:
            drift.append(
                f"{reference}: expected ({expected_x:.3f}, {expected_y:.3f}, {expected_rotation:.1f}deg), "
                f"got ({actual_x:.3f}, {actual_y:.3f}, {actual_rotation:.1f}deg)"
            )
    if drift:
        raise ValueError("session placement does not match board:\n" + "\n".join(drift))


def import_session(board, session: list[object]) -> tuple[int, int]:
    validate_placement(board, session)
    routes = child(session, "routes")
    resolution = child(routes, "resolution")
    if len(resolution) != 3 or resolution[1] != "um":
        raise ValueError(f"unsupported session resolution: {resolution}")
    units_per_mm = float(str(resolution[2])) * 1000.0
    network = child(routes, "network_out")
    track_count = 0
    via_count = 0

    for net_node in network[1:]:
        if not isinstance(net_node, list) or len(net_node) < 2 or net_node[0] != "net":
            continue
        net_name = str(net_node[1])
        net = board.FindNet(net_name)
        if net is None:
            raise ValueError(f"session references unknown net {net_name!r}")
        for item in net_node[2:]:
            if not isinstance(item, list) or not item:
                continue
            if item[0] == "wire":
                path = child(item, "path")
                layer_name = str(path[1])
                if layer_name not in LAYERS:
                    raise ValueError(f"unsupported copper layer {layer_name!r}")
                width = coordinate(path[2], units_per_mm)
                values = path[3:]
                if len(values) < 4 or len(values) % 2:
                    raise ValueError(f"invalid path for {net_name}: {path}")
                points = [
                    pcbnew.VECTOR2I(
                        coordinate(values[index], units_per_mm),
                        -coordinate(values[index + 1], units_per_mm),
                    )
                    for index in range(0, len(values), 2)
                ]
                for start, end in pairwise(points):
                    if start == end:
                        continue
                    track = pcbnew.PCB_TRACK(board)
                    track.SetNet(net)
                    track.SetLayer(LAYERS[layer_name])
                    track.SetWidth(width)
                    track.SetStart(start)
                    track.SetEnd(end)
                    board.Add(track)
                    track_count += 1
            elif item[0] == "via":
                if len(item) < 4:
                    raise ValueError(f"invalid via for {net_name}: {item}")
                via = pcbnew.PCB_VIA(board)
                via.SetNet(net)
                via.SetPosition(
                    pcbnew.VECTOR2I(
                        coordinate(item[2], units_per_mm),
                        -coordinate(item[3], units_per_mm),
                    )
                )
                diameter, drill = via_dimensions(item[1])
                via.SetWidth(pcbnew.FromMM(diameter))
                via.SetDrill(pcbnew.FromMM(drill))
                board.Add(via)
                via_count += 1
    return track_count, via_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a Freerouting SES file into a KiCad board")
    parser.add_argument("board", type=Path)
    parser.add_argument("session", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    board = pcbnew.LoadBoard(str(args.board.resolve()))
    session = parse_session(args.session.read_text(encoding="utf-8"))
    tracks, vias = import_session(board, session)
    board.Save(str(args.output.resolve()))
    print(f"saved {args.output}: {tracks} track segments, {vias} vias")


if __name__ == "__main__":
    main()
