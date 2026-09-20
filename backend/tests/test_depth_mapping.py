"""The FSR-pressure -> tip-height mapping in TagFsrInput.cs must let a person work every layer.

The C# defaults are parsed from the source and mirrored here, then driven through the real simulator, so a
change to either side that breaks the procedure fails this test.
"""
from __future__ import annotations

import os
import re

import pytest

from helpers import IDENTITY, run, sample
from surge_prep.layered_chest import CONTACT_THRESHOLD_MM, LAYER_BOTTOMS_MM, LayeredChestState
from surge_prep.models import CalibrationCreate, SessionCreate
from surge_prep.service import TrainingService
from surge_prep.simulation import MemorySimulator
from surge_prep.store import MemoryStore

SOURCE = os.path.join(os.path.dirname(__file__), "..", "..", "client", "unity", "Packages",
                      "com.surgeprep.runtime", "Runtime", "TagFsrInput.cs")


def _floats(text):
    return [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", text)]


def _load():
    source = open(SOURCE, encoding="utf-8").read()
    scalar = lambda name: float(re.search(rf"float {name} = (-?[\d.]+)f", source).group(1))
    points = _floats(re.search(r"float\[\] pressurePoints = \{([^}]*)\}", source).group(1))
    depths = _floats(re.search(r"float\[\] depthMm = \{([^}]*)\}", source).group(1))
    return scalar("hoverMm"), scalar("touchPressure"), points, depths


HOVER, TOUCH, POINTS, DEPTHS = _load()


def tip_height(pressed: float) -> float:
    """Python mirror of TagFsrInput.TipHeightMm."""
    pressed = max(0.0, min(1.0, pressed))
    if pressed <= TOUCH:
        return HOVER * (1 - pressed / TOUCH)
    if pressed >= POINTS[-1]:
        return -DEPTHS[-1]
    for i in range(1, len(POINTS)):
        if pressed <= POINTS[i]:
            t = (pressed - POINTS[i - 1]) / (POINTS[i] - POINTS[i - 1])
            return -(DEPTHS[i - 1] + (DEPTHS[i] - DEPTHS[i - 1]) * t)
    return -DEPTHS[-1]


# ---------------------------------------------------------------- the curve itself


def test_control_points_are_valid():
    assert len(POINTS) == len(DEPTHS) >= 4
    assert POINTS == sorted(POINTS) and len(set(POINTS)) == len(POINTS)
    assert DEPTHS == sorted(DEPTHS)
    assert POINTS[0] == pytest.approx(TOUCH) and DEPTHS[0] == 0
    assert POINTS[-1] == 1.0
    assert DEPTHS[-1] < -LAYER_BOTTOMS_MM["pleura"] + 0.01 or DEPTHS[-1] < 32.0     # never past the fixed floor


def test_no_pressure_hovers_and_touch_reaches_the_skin():
    assert tip_height(0.0) == HOVER
    assert tip_height(TOUCH) == pytest.approx(0.0)


def test_height_never_increases_with_pressure():
    heights = [tip_height(p / 200) for p in range(201)]
    assert all(a >= b for a, b in zip(heights, heights[1:]))


def test_a_light_touch_makes_contact():
    """The reported bug: a light touch used to leave the tip 2 to 6 mm above the skin."""
    assert tip_height(0.0) > 0                       # no pressure: hovering, no contact
    assert -tip_height(0.06) >= CONTACT_THRESHOLD_MM     # a light press is already in contact


def test_each_layer_gets_a_wide_slice_of_the_pressure_range():
    def span(shallow, deep):
        """Width of the pressure range whose tip depth (mm below the skin) is between shallow and deep."""
        pressures = [p / 1000 for p in range(1001) if shallow <= -tip_height(p / 1000) < deep]
        return (max(pressures) - min(pressures)) if pressures else 0

    assert span(CONTACT_THRESHOLD_MM, 3.0) > 0.15         # skin: was about 0.075 of the range with the old linear map
    assert span(3.0, 10.0) > 0.15                         # fat
    assert span(15.0, 22.0) > 0.15                        # muscle
    assert span(25.0, 32.0) > 0.15                        # pleura


def test_skin_zone_keeps_the_scalpel_inside_the_skin():
    zone = [p / 1000 for p in range(1001) if 0 < -tip_height(p / 1000) < 3.0]
    assert zone and all(LayeredChestState.layer_at_height(tip_height(p)) == "skin" for p in zone)


@pytest.mark.parametrize("pressure,layer", [(0.10, "skin"), (0.35, "subcutaneous"), (0.65, "intercostal-muscle"),
                                            (0.90, "pleura")])
def test_pressure_selects_the_expected_layer(pressure, layer):
    assert LayeredChestState.layer_at_height(tip_height(pressure)) == layer


def test_layer_lookup_is_by_absolute_height():
    assert LayeredChestState.layer_at_height(2.0) == "skin"
    assert LayeredChestState.layer_at_height(-2.9) == "skin"
    assert LayeredChestState.layer_at_height(-3.1) == "subcutaneous"
    assert LayeredChestState.layer_at_height(-15.1) == "intercostal-muscle"
    assert LayeredChestState.layer_at_height(-25.1) == "pleura"
    assert LayeredChestState.layer_at_height(-99) == "pleura"


# ---------------------------------------------------------------- the whole procedure through the simulator


async def _stroke(service, session, cal, seq, pressure, tool, half_length=16.0, steps=64):
    snaps = []
    for i in range(steps):
        x = -half_length + 2 * half_length * i / (steps - 1)
        snaps.append(await service.process_sample(session.session_id, sample(
            session, cal, seq + i, x, tip_height(pressure), 0.0, tool=tool, force=1.0, contact=True)))
    return snaps, seq + steps


async def _procedure(plan):
    service = TrainingService(MemoryStore(), MemorySimulator())
    cal = await service.create_calibration(CalibrationCreate(device_id="demo", transform=IDENTITY, rms_error_mm=0.1))
    session = await service.create_session(SessionCreate(
        exercise_id="chest-tube-access-demo", calibration_id=cal.calibration_id, tool_id="scalpel", device_id="demo"))
    seq, all_snaps = 0, []
    for index, (tool, pressure) in enumerate(plan):
        # deeper strokes stay inside the opening made above them: past its ends the tip presses on intact tissue
        snaps, seq = await _stroke(service, session, cal, seq, pressure, tool, half_length=16.0 if index == 0 else 11.0)
        all_snaps.extend(snaps)
    return all_snaps


FULL_PLAN = [("scalpel", 0.10), ("blunt-dissector", 0.35), ("blunt-dissector", 0.65), ("scalpel", 0.90),
             ("chest-tube", 0.95)]


def test_a_person_can_complete_every_layer_with_the_mapping():
    snaps = run(_procedure(FULL_PLAN))
    opened = {layer.layer_id: layer.opened for layer in snaps[-1].tissue.layers}
    assert opened == {"skin": True, "subcutaneous": True, "intercostal-muscle": True, "pleura": True}
    assert snaps[-1].procedure_stage == "complete"
    events = {e for s in snaps for e in s.events}
    assert "layer-violation" not in events and "excessive-force" not in events


def test_a_light_touch_alone_cuts_the_skin():
    snaps = run(_procedure([("scalpel", 0.06)]))
    assert snaps[-1].tool.contact is True
    assert snaps[-1].tissue.incision_length_mm > 20


def test_hovering_never_cuts():
    snaps = run(_procedure([("scalpel", 0.0), ("scalpel", 0.02)]))
    assert not any(s.tool.contact for s in snaps)
    assert snaps[-1].tissue.incision_length_mm == 0


def test_pressing_straight_to_the_fat_with_the_scalpel_is_a_layer_violation():
    snaps = run(_procedure([("scalpel", 0.35)]))
    assert any("layer-violation" in s.events for s in snaps)
    assert snaps[-1].tissue.incision_length_mm == 0        # the skin was skipped, so nothing opened


def test_muscle_can_be_opened_after_the_skin_is_open():
    """Regression: the layer was chosen from depth below the exposed surface, so muscle looked like skin."""
    snaps = run(_procedure(FULL_PLAN[:3]))
    assert {layer.layer_id: layer.opened for layer in snaps[-1].tissue.layers}["intercostal-muscle"] is True
