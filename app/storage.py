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


APP_STATE_PATH = DATA_DIR / "app_state.json"


def load_app_state() -> dict:
    if not APP_STATE_PATH.exists():
        return {}
    with open(APP_STATE_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_app_state(state: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(APP_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# Identitätsfarben für Personen — strikt getrennt von Status-/Ampelfarben.
QUAL_PALETTE = ["#2196A6", "#E07B39", "#6A5ACD", "#2E8B57", "#C0392B",
                "#8B6914", "#1565C0", "#AD1457"]


def person_colors(project_name: str, config: dict) -> dict:
    """Feste Farbe pro Person, in project.json persistiert, damit die Zuordnung
    stabil bleibt, wenn Teilnehmer dazukommen oder wegfallen."""
    colors = dict(config.get("person_colors", {}))
    names = list(config.get("participants", []))
    names += [n for n in config.get("inactive_participants", {}) if n not in names]
    changed = False
    for n in names:
        if n not in colors:
            used = set(colors.values())
            free = next((c for c in QUAL_PALETTE if c not in used),
                        QUAL_PALETTE[len(colors) % len(QUAL_PALETTE)])
            colors[n] = free
            changed = True
    if changed:
        config["person_colors"] = colors
        save_project(project_name, config)
    return colors


def new_session_template(config: dict, session_date: str = None) -> dict:
    participants = {
        p: {
            "notwendig": False,
            "optional": False,
            "anwesend": False,
            "verzug_min": 0,
            "frueher_raus_min": 0,
            "anwesend_min": 0,
            "rolle": "aktiv",
            "behavior": {m["key"]: 0 for m in config.get("behavior_metrics", [])},
        }
        for p in config.get("participants", [])
    }
    return {
        "date": session_date or str(date.today()),
        "meeting_metrics": {m["key"]: 0 for m in config.get("meeting_metrics", [])},
        "participants": participants,
        "notes": {n["key"]: "" for n in config.get("note_categories", [])},
        "meeting_owner": "",
        "protokollant": "",
    }


DEFAULT_CONFIG = {
    "participants": [],
    "inactive_participants": {},
    "dashboard_metrics": [],
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
