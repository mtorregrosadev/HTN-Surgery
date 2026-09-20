"""scripts/coach.py against the real FastAPI app (in-process), plus error paths."""
from __future__ import annotations

import os
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import coach as coach_cli  # noqa: E402

from surge_prep.app import create_app  # noqa: E402
from surge_prep.coaching import ElevenLabsVoice, OfflineCoach  # noqa: E402
from surge_prep.simulation import MemorySimulator  # noqa: E402
from surge_prep.store import MemoryStore  # noqa: E402
from test_api_features import StubVoice, finish_session, start_session  # noqa: E402


@pytest.fixture
def api():
    with TestClient(create_app(MemoryStore(), MemorySimulator(), coach=OfflineCoach(), voice=StubVoice()),
                    base_url="http://api") as client:
        yield client


def test_latest_prints_a_report(api, capsys):
    finish_session(api)
    assert coach_cli.main(["--latest"], client=api) == 0
    out = capsys.readouterr().out
    assert "Training score" in out and "Next drill:" in out and "Not a clinical assessment" in out


def test_session_id_is_used(api, capsys):
    session_id, _ = finish_session(api)
    assert coach_cli.main(["--session", session_id], client=api) == 0
    assert "What to work on" in capsys.readouterr().out


def test_latest_skips_unfinished_sessions(api, capsys):
    finished, _ = finish_session(api)
    start_session(api)                                   # newer but still active
    assert coach_cli.main(["--latest"], client=api) == 0
    assert "Training score" in capsys.readouterr().out


def test_latest_with_nothing_finished_fails_politely(api, capsys):
    start_session(api)
    assert coach_cli.main(["--latest"], client=api) == 1
    assert "No completed session" in capsys.readouterr().err


def test_unfinished_and_unknown_sessions(api, capsys):
    active, _ = start_session(api)
    assert coach_cli.main(["--session", active], client=api) == 1
    assert "not finished" in capsys.readouterr().err
    assert coach_cli.main(["--session", "nope"], client=api) == 1
    assert "not found" in capsys.readouterr().err


def test_speak_saves_and_plays_audio(api, tmp_path, capsys):
    finish_session(api)
    played = []
    out = tmp_path / "coach.mp3"
    code = coach_cli.main(["--latest", "--speak", "--out", str(out)], client=api, player=played.append)
    assert code == 0
    assert out.read_bytes() == b"MP3DATA"
    assert played == [str(out)]
    assert "Saved audio" in capsys.readouterr().out


def test_speak_without_a_voice_key_reports_it():
    with TestClient(create_app(MemoryStore(), MemorySimulator(), coach=OfflineCoach(), voice=ElevenLabsVoice(None)),
                    base_url="http://api") as client:
        finish_session(client)
        played = []
        assert coach_cli.main(["--latest", "--speak"], client=client, player=played.append) == 2
        assert played == []


def test_progress_output(api, capsys):
    for _ in range(2):
        finish_session(api)
    assert coach_cli.main(["--progress"], client=api) == 0
    out = capsys.readouterr().out
    assert "Attempts: 2" in out and "Weakest area" in out and "Trend:" in out


def test_progress_with_no_attempts(api, capsys):
    assert coach_cli.main(["--progress"], client=api) == 0
    assert "No completed attempts" in capsys.readouterr().out


def test_unreachable_api_is_reported(capsys):
    def refuse(request):
        raise httpx.ConnectError("refused")

    client = httpx.Client(base_url="http://127.0.0.1:1", transport=httpx.MockTransport(refuse))
    assert coach_cli.main(["--latest"], client=client) == 3
    assert "Could not reach the API" in capsys.readouterr().err


def test_arguments_are_required_and_exclusive():
    with pytest.raises(SystemExit):
        coach_cli.main([])
    with pytest.raises(SystemExit):
        coach_cli.main(["--latest", "--progress"])
