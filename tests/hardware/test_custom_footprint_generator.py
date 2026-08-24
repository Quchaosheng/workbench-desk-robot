from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class Vector:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


class LayerSet:
    def __init__(self):
        self.layers = set()

    def AddLayer(self, layer):
        self.layers.add(layer)

    @classmethod
    def AllCuMask(cls):
        return cls()


class Pad:
    def __init__(self, _footprint):
        self.position = Vector(0, 0)
        self.size = Vector(0, 0)

    def SetNumber(self, number):
        self.number = number

    def SetPosition(self, position):
        self.position = position

    def SetSize(self, size):
        self.size = size

    def SetAttribute(self, attribute):
        self.attribute = attribute

    def SetShape(self, shape):
        self.shape = shape

    def SetRoundRectRadiusRatio(self, ratio):
        self.ratio = ratio

    def SetLayerSet(self, layers):
        self.layers = layers

    def SetDrillSize(self, drill):
        self.drill = drill

    def GetPosition(self):
        return self.position

    def GetSize(self):
        return self.size


class Shape:
    def __init__(self, _footprint):
        pass

    def SetShape(self, shape):
        self.shape = shape

    def SetStart(self, start):
        self.start = start

    def SetEnd(self, end):
        self.end = end

    def SetLayer(self, layer):
        self.layer = layer

    def SetWidth(self, width):
        self.width = width


class Field:
    def SetPosition(self, position):
        self.position = position

    def SetVisible(self, visible):
        self.visible = visible


class Footprint:
    def __init__(self, _board):
        self.items = []
        self.reference = Field()
        self.value = Field()

    def SetFPID(self, fpid):
        self.fpid = fpid

    def SetAttributes(self, attributes):
        self.attributes = attributes

    def SetReference(self, reference):
        self.reference_text = reference

    def SetValue(self, value):
        self.value_text = value

    def SetLibDescription(self, description):
        self.description = description

    def Reference(self):
        return self.reference

    def Value(self):
        return self.value

    def Add(self, item):
        self.items.append(item)

    def Pads(self):
        return [item for item in self.items if isinstance(item, Pad)]


def fake_pcbnew():
    return types.SimpleNamespace(
        VECTOR2I=Vector,
        LSET=LayerSet,
        PAD=Pad,
        PCB_SHAPE=Shape,
        FOOTPRINT=Footprint,
        BOARD=object,
        LIB_ID=lambda library, name: (library, name),
        FromMM=lambda value: value,
        ToMM=lambda value: value,
        F_Cu="F.Cu",
        F_Paste="F.Paste",
        F_Mask="F.Mask",
        B_Mask="B.Mask",
        F_Fab="F.Fab",
        F_CrtYd="F.CrtYd",
        F_SilkS="F.SilkS",
        PAD_ATTRIB_SMD="pad-smd",
        PAD_ATTRIB_PTH="pad-pth",
        PAD_SHAPE_ROUNDRECT="roundrect",
        PAD_SHAPE_CIRCLE="circle",
        PAD_SHAPE_OVAL="oval",
        SHAPE_T_RECT="rect",
        SHAPE_T_SEGMENT="segment",
        FP_SMD="footprint-smd",
        FP_THROUGH_HOLE="footprint-tht",
    )


def load_generator(monkeypatch):
    monkeypatch.setitem(sys.modules, "pcbnew", fake_pcbnew())
    path = ROOT / "hardware/pcb/tools/generate_footprints.py"
    spec = importlib.util.spec_from_file_location("custom_footprint_generator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_all_custom_footprints_have_type_silkscreen_pin1_and_courtyard(monkeypatch) -> None:
    generator = load_generator(monkeypatch)
    expected = {
        "microfit": generator.pcbnew.FP_THROUGH_HOLE,
        "fuse_4510": generator.pcbnew.FP_SMD,
        "sense_3637": generator.pcbnew.FP_SMD,
        "isolated_power_tbd": generator.pcbnew.FP_THROUGH_HOLE,
        "rpl_5": generator.pcbnew.FP_SMD,
        "tps26633": generator.pcbnew.FP_SMD,
        "iso1042_dw16_hv": generator.pcbnew.FP_SMD,
        "act45b": generator.pcbnew.FP_SMD,
        "can_tvs": generator.pcbnew.FP_SMD,
        "sfm4": generator.pcbnew.FP_THROUGH_HOLE,
    }

    for factory_name, attribute in expected.items():
        footprint = getattr(generator, factory_name)()
        silk = [item for item in footprint.items if isinstance(item, Shape) and item.layer == "F.SilkS"]
        courtyard = [item for item in footprint.items if isinstance(item, Shape) and item.layer == "F.CrtYd"]
        assert footprint.attributes == attribute, factory_name
        assert len(silk) >= 3, factory_name  # clipped body plus two-stroke pin-1 marker
        assert len(courtyard) == 1, factory_name


def test_polarity_and_connector_key_markers_add_dedicated_silk(monkeypatch) -> None:
    generator = load_generator(monkeypatch)
    marker = generator.new_footprint("Marker", 10.0, 10.0, attribute=generator.pcbnew.FP_SMD)

    generator.add_pin1_marker(marker, 10.0, 10.0)
    generator.add_polarity_marker(marker, 10.0)
    generator.add_connector_key_marker(marker, 10.0)
    silk = [item for item in marker.items if isinstance(item, Shape) and item.layer == "F.SilkS"]
    assert len(silk) == 6

    polarity_calls = []
    key_calls = []
    add_polarity_marker = generator.add_polarity_marker
    add_connector_key_marker = generator.add_connector_key_marker

    def track_polarity(footprint, height):
        polarity_calls.append(footprint.value_text)
        add_polarity_marker(footprint, height)

    def track_key(footprint, height):
        key_calls.append(footprint.value_text)
        add_connector_key_marker(footprint, height)

    monkeypatch.setattr(generator, "add_polarity_marker", track_polarity)
    monkeypatch.setattr(generator, "add_connector_key_marker", track_key)

    generator.fuse_4510()
    generator.can_tvs()
    generator.isolated_power_tbd()
    generator.microfit()
    assert polarity_calls == ["CAN_TVS", "Isolated_48V_12V_240W_TBD"]
    assert key_calls == ["MicroFit_2x2"]


def test_isolated_power_placeholder_is_nine_pin_tht_and_not_production(monkeypatch) -> None:
    generator = load_generator(monkeypatch)

    assert not hasattr(generator, "dcm3623")
    footprint = generator.isolated_power_tbd()
    pads = {int(pad.number): pad for pad in footprint.Pads()}

    assert footprint.value_text == "Isolated_48V_12V_240W_TBD"
    assert footprint.attributes == generator.pcbnew.FP_THROUGH_HOLE
    assert set(pads) == set(range(1, 10))
    assert all(pad.attribute == generator.pcbnew.PAD_ATTRIB_PTH for pad in pads.values())
    assert all(pad.drill.x > 0 and pad.drill.y > 0 for pad in pads.values())
    assert "NOT FOR PRODUCTION" in footprint.description

    silk = [item for item in footprint.items if isinstance(item, Shape) and item.layer == "F.SilkS"]
    assert len(silk) >= 6  # body, pin-1 marker, and the dedicated polarity marker


def test_iso1042_hv_land_pattern_preserves_ti_clearance(monkeypatch) -> None:
    generator = load_generator(monkeypatch)
    footprint = generator.iso1042_dw16_hv()
    pads = {int(pad.number): pad for pad in footprint.Pads()}

    assert len(pads) == 16
    assert pads[1].position.x == -4.875
    assert pads[16].position.x == 4.875
    assert pads[1].position.y == pads[16].position.y == -4.445
    assert pads[8].position.y == pads[9].position.y == 4.445
    assert pads[1].size.x == pads[16].size.x == 1.65
    assert pads[1].size.y == pads[16].size.y == 0.60

    copper_edge_clearance = (pads[16].position.x - pads[16].size.x / 2) - (pads[1].position.x + pads[1].size.x / 2)
    assert copper_edge_clearance == 8.1
