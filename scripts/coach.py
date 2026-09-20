"""Fetch AI coaching for a finished practice run and (optionally) hear it spoken.

  python scripts/coach.py --latest                 # coach the most recent completed session
  python scripts/coach.py --session session-abc    # coach a specific session
  python scripts/coach.py --latest --speak         # also save + play the ElevenLabs audio
  python scripts/coach.py --progress               # scores across all attempts (stored in MongoDB)

Needs the API running (default http://127.0.0.1:8000). Set OPENAI_API_KEY or GEMINI_API_KEY on the API
for AI wording (otherwise the built-in rubric coach answers) and ELEVENLABS_API_KEY for --speak.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile

import httpx


def play(path: str) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)                                     # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)


def find_latest_completed(client: httpx.Client) -> str | None:
    sessions = client.get("/v1/sessions", params={"limit": 50}).json()
    for session in sessions:
        if session.get("status") == "completed":
            return session["sessionId"]
    return None


def print_report(report: dict) -> None:
    print(f"\nTraining score: {report['scorePercent']:.0f}%   (coach: {report['provider']})")
    print(report["summary"])
    print("\nWhat went well")
    for line in report["strengths"]:
        print(f"  + {line}")
    print("\nWhat to work on")
    for line in report["improvements"]:
        print(f"  - {line}")
    print(f"\nNext drill: {report['nextDrill']}")
    if report.get("note"):
        print(f"\n(note: {report['note']})")
    print(f"\n{report['disclaimer']}")


def print_progress(progress: dict) -> None:
    if not progress["attempts"]:
        print("No completed attempts yet.")
        return
    print(f"Attempts: {progress['attempts']}   latest {progress['latestScorePercent']}%   "
          f"best {progress['bestScorePercent']}%   average {progress['averageScorePercent']}%")
    if progress.get("improvementPoints") is not None:
        print(f"Change since the first attempt: {progress['improvementPoints']:+.1f} points")
    print(f"Weakest area so far: {progress['weakestComponent']}")
    print("Trend: " + "  ".join(f"{p['scorePercent']:.0f}" for p in progress["trend"]))


def main(argv: list[str] | None = None, client: httpx.Client | None = None, player=play) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--session")
    group.add_argument("--latest", action="store_true")
    group.add_argument("--progress", action="store_true")
    parser.add_argument("--speak", action="store_true", help="also fetch and play spoken coaching")
    parser.add_argument("--out", help="where to save the audio (default: a temp file)")
    args = parser.parse_args(argv)
    if not (args.session or args.latest or args.progress):
        parser.error("choose --latest, --session ID or --progress")

    owns_client = client is None
    client = client or httpx.Client(base_url=args.api, timeout=60.0)
    try:
        if args.progress:
            response = client.get("/v1/progress")
            response.raise_for_status()
            print_progress(response.json())
            return 0

        session_id = args.session or find_latest_completed(client)
        if not session_id:
            print("No completed session found. Finish a practice run first.", file=sys.stderr)
            return 1
        response = client.post(f"/v1/sessions/{session_id}/coaching")
        if response.status_code == 409:
            print("That session is not finished yet. Leave Play mode to complete it.", file=sys.stderr)
            return 1
        if response.status_code == 404:
            print(f"Session {session_id} was not found.", file=sys.stderr)
            return 1
        response.raise_for_status()
        print_report(response.json())

        if args.speak:
            audio = client.post(f"/v1/sessions/{session_id}/coaching/audio")
            if audio.status_code >= 400:
                print(f"\nSpoken coaching unavailable: {audio.json().get('detail', audio.status_code)}",
                      file=sys.stderr)
                return 2
            path = args.out or os.path.join(tempfile.gettempdir(), f"{session_id}-coaching.mp3")
            with open(path, "wb") as f:
                f.write(audio.content)
            print(f"\nSaved audio to {path}")
            player(path)
        return 0
    except httpx.ConnectError:
        print(f"Could not reach the API at {args.api}. Is it running?", file=sys.stderr)
        return 3
    finally:
        if owns_client:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
