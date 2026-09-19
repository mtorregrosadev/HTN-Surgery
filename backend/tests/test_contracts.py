import json
from pathlib import Path

import jsonschema
from surge_prep.models import SimulationSnapshot, ToolSample

ROOT = Path(__file__).resolve().parents[2]
V1 = ROOT / "contracts" / "v1"
V11 = ROOT / "contracts" / "v1.1"

SAMPLE_1_0 = {
    "contractVersion": "1.0",
    "sessionId": "session-1",
    "toolId": "blunt-stylus-1",
    "deviceId": "esp32-1",
    "calibrationId": "cal-1",
    "sequence": 0,
    "timestampMs": 0,
    "positionMm": {"x": 0, "y": 10, "z": 0},
    "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1},
    "forceN": 0.7,
    "contact": True,
}

SAMPLE_1_1 = {
    **SAMPLE_1_0,
    "contractVersion": "1.1",
    "toolId": "scalpel",
    "forceN": 0,
    "contact": False,
    "inputMode": "pose-only",
    "forceMeasurementValid": False,
    "quality": 1,
    "sourceHealthy": True,
}

SNAPSHOT_1_0 = {
    "contractVersion": "1.0",
    "sessionId": "session-1",
    "tick": 1,
    "simulationTimeMs": 10,
    "tool": {
        "positionMm": {"x": 0, "y": 10, "z": 0},
        "orientation": {"qx": 0, "qy": 0, "qz": 0, "qw": 1},
        "forceN": 0.7,
        "contact": True,
    },
    "tissue": {
        "deformationMm": 1.0,
        "incisionProgress": 0,
        "incisionLengthMm": 0,
        "incisionDepthMm": 0,
        "interactionMode": "contact",
    },
    "deformableMeshes": [
        {
            "objectId": "training-membrane",
            "topologyRevision": 1,
            "verticesMm": [{"x": 0, "y": 0, "z": 0}, {"x": 1, "y": 0, "z": 0}, {"x": 0, "y": 0, "z": 1}],
            "triangleIndices": [0, 1, 2],
        }
    ],
    "events": ["contact-start"],
}

SNAPSHOT_1_1 = {
    **SNAPSHOT_1_0,
    "contractVersion": "1.1",
    "simulationBackend": "sofa-native",
    "procedureStage": "skin-incision",
    "sessionDegraded": False,
    "tool": {
        **SNAPSHOT_1_0["tool"],
        "forceN": 0.4,
        "contactPointMm": {"x": 0, "y": 0, "z": 0},
        "contactNormal": {"x": 0, "y": 1, "z": 0},
        "reactionForceN": 0.4,
        "penetrationDepthMm": 1.2,
    },
    "tissue": {
        **SNAPSHOT_1_0["tissue"],
        "activeLayer": "skin",
        "layers": [
            {
                "layerId": "skin",
                "opened": False,
                "openingProgress": 0.1,
                "deformationMm": 1.0,
            }
        ],
    },
}


def _schema(path: Path) -> dict:
    return json.loads(path.read_text())


def test_v1_schema_accepts_stored_1_0_sample():
    jsonschema.validate(SAMPLE_1_0, _schema(V1 / "tool-sample.schema.json"))


def test_v11_schema_accepts_1_0_and_1_1_samples():
    schema = _schema(V11 / "tool-sample.schema.json")
    jsonschema.validate(SAMPLE_1_0, schema)
    jsonschema.validate(SAMPLE_1_1, schema)


def test_v11_schema_accepts_1_0_and_1_1_snapshots():
    schema = _schema(V11 / "simulation-snapshot.schema.json")
    jsonschema.validate(SNAPSHOT_1_0, schema)
    jsonschema.validate(SNAPSHOT_1_1, schema)


def test_models_parse_stored_1_0_and_new_1_1_payloads():
    sample_10 = ToolSample.model_validate(SAMPLE_1_0)
    sample_11 = ToolSample.model_validate(SAMPLE_1_1)
    assert sample_10.contract_version == "1.0"
    assert sample_11.input_mode == "pose-only"
    snapshot_10 = SimulationSnapshot.model_validate(SNAPSHOT_1_0)
    snapshot_11 = SimulationSnapshot.model_validate(SNAPSHOT_1_1)
    assert snapshot_10.procedure_stage == "approach"
    assert snapshot_11.simulation_backend == "sofa-native"
    assert snapshot_11.tissue.active_layer == "skin"
