import json
import os
from pathlib import Path
from datetime import date

DATA_DIR = Path(__file__).parent.parent / "data"


def list_projects() -> list[str]:
    if not DATA_DIR.exists():
        return []
    return [d.name for d in DATA_DIR.iterdir() if d.is_dir() and (d / "project.json").exists()]


def load_project(name: str) -> dict:
    path = DATA_DIR / name / "project.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_project(name: str, config: dict):
    project_dir = DATA_DIR / name
    project_dir.mkdir(parents=True, exist_ok=True)
    with open(project_dir / "project.json", "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def load_sessions(project_name: str) -> list[dict]:
    path = DATA_DIR / project_name / "sessions.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_sessions(project_name: str, sessions: list[dict]):
    path = DATA_DIR / project_name / "sessions.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)


def save_session(project_name: str, session: dict):
    sessions = load_sessions(project_name)
    existing = next((i for i, s in enumerate(sessions) if s["date"] == session["date"]), None)
    if existing is not None:
        sessions[existing] = session
    else:
        sessions.append(session)
    sessions.sort(key=lambda s: s["date"])
    save_sessions(project_name, sessions)


def delete_session(project_name: str, session_date: str):
    sessions = load_sessions(project_name)
    sessions = [s for s in sessions if s["date"] != session_date]
    save_sessions(project_name, sessions)


def new_session_template(config: dict, session_date: str = None) -> dict:
    participants = {
        p: {
            "notwendig": False,
            "optional": False,
            "anwesend": False,
            "verzug_min": 0,
            "frueher_raus_min": 0,
            "anwesend_min": 0,
            "behavior": {m["key"]: 0 for m in config.get("behavior_metrics", [])},
        }
        for p in config.get("participants", [])
    }
    return {
        "date": session_date or str(date.today()),
        "meeting_metrics": {m["key"]: 0 for m in config.get("meeting_metrics", [])},
        "participants": participants,
        "notes": {n["key"]: "" for n in config.get("note_categories", [])},
    }


DEFAULT_CONFIG = {
    "participants": [],
    "behavior_metrics": [
        {"key": "konstruktiv", "label": "Konstruktiv"},
        {"key": "unterbrechung", "label": "Unterbrechung"},
        {"key": "geringschaetzend", "label": "Geringschätzend"},
        {"key": "hand_gehoben", "label": "Hand gehoben"},
    ],
    "meeting_metrics": [
        {"key": "dauer_min", "label": "Meetingdauer (Min)"},
    ],
    "note_categories": [
        {"key": "organisatorisches", "label": "Organisatorisches"},
        {"key": "soziales", "label": "Soziales & Emotionales"},
        {"key": "verbesserungen", "label": "Verbesserungsvorschläge"},
    ],
}
