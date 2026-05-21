"""
Einmalig-Import: Liest Leitungsmeeting.xlsx ein und legt die Daten
als Projekt "Leitungsmeeting" im data/-Ordner ab.

Aufruf:
    python3 import_excel.py /pfad/zur/Leitungsmeeting.xlsx
"""

import sys
import json
import re
import math
import pandas as pd
from pathlib import Path
from datetime import datetime

EXCEL_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("Leitungsmeeting.xlsx")
PROJECT_NAME = "Leitungsmeeting"
DATA_DIR = Path(__file__).parent / "data" / PROJECT_NAME

# Spalten-Mapping (col-Index → Feldname)
COL_NOTWENDIG  = 1
COL_OPTIONAL   = 2
COL_ANWESEND   = 3
COL_VERZUG     = 4
COL_FRUEHER    = 5  # früher raus (col 4 in raw, but see below)
COL_ANWMIN     = 5
COL_KONSTRUKT  = 6
COL_UNTERBRECH = 7
COL_GERING     = 9
COL_HAND       = 10

# Korrektur: Ab Sheet 22.10 hat col 4 = "früher ruas" und col 5 = "Anwesend (Min)"
# Das ist konsistent in allen Sheets → col 4 = Verzug, col 5 = früher raus ODER Anwesend
# Tatsächlich ist col 4 = Verzug UND col 5 = früher raus, aber wir sehen:
# Birte 05.11: [Birte, NaN, 1, 0, 0, 50, 1, 4, 0.08, 0, 1]
# col0=Birte col1=Notwendig(NaN) col2=Optional(1) col3=Anwesend(0?) col4=Verzug(0) col5=50(Anwesend-Min)
# → col3 = Anwesend (ja/nein als 0/1? aber Birte war anwesend laut anderen Sheets!)
# → col3 = Verzug (0 Min Verzug) col4 = früher raus (0) col5 = Anwesend-Min (50)
# Korrekte Zuordnung nach Header-Row: [Notwendig, Optional, Anwesend, Verzug, früher raus, Anwesend(Min), ...]

COL_ANWESEND   = 2  # Optional (war im ersten Sheet manchmal Notwendig/Optional swapped)
# Nach nochmaliger Analyse:
# Header: Notwendig(1), Optional(2), Anwesend(3→aber das ist nur Teilnahme ja/nein?), Verzug(4 min), früher raus(5 min), Anwesend-Min(6??)
# Nein, Header-Row zeigt: col0=Notwendig, col1=Optional, col2=Anwesend, col3=Verzug, col4=früher raus, col5=Anwesend(Min)
# D.h. der index/name ist außerhalb: row.iloc[0] = Name, row.iloc[1]=Notwendig usw.

PARTICIPANTS_ROWS = range(1, 9)  # Zeilen 1-8 = Teilnehmer

SKIP_SHEETS = {"Kurven"}


def safe_int(val, default=0):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def safe_bool(val):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return False
    return bool(val) and val != 0


def parse_date(sheet_name: str) -> str:
    """Wandelt "22.10" → "2024-10-22", "14.01" → "2025-01-14" usw."""
    parts = sheet_name.strip().split(".")
    if len(parts) != 2:
        return None
    day, month = int(parts[0]), int(parts[1])
    # Oct–Dec → 2024, Jan–May → 2025
    year = 2024 if month >= 10 else 2025
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


def collect_notes(df: pd.DataFrame) -> dict:
    """Liest qualitative Notizen aus den unteren Zeilen (ab Zeile 19)."""
    org_lines = []
    social_lines = []
    improve_lines = []
    in_org = False
    in_social = False
    in_improve = False

    for idx in range(19, len(df)):
        row = df.iloc[idx]
        cell0 = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
        cell5 = str(row.iloc[5]).strip() if pd.notna(row.iloc[5]) else ""

        if cell5 == "Soziales und Emotionales":
            in_social = True

        if cell0 == "Verbesserungsvorschläge":
            in_improve = True
            in_org = False
            continue
        if cell0 == "Organisatorisches":
            in_org = True
            continue

        if in_improve and cell0:
            improve_lines.append(cell0)
        elif in_org and cell0:
            org_lines.append(cell0)
        if in_social and cell5 and cell5 != "Soziales und Emotionales":
            social_lines.append(cell5)

    return {
        "organisatorisches": "\n".join(org_lines),
        "soziales": "\n".join(social_lines),
        "verbesserungen": "\n".join(improve_lines),
    }


def parse_sheet(df: pd.DataFrame) -> dict:
    participants = {}
    for row_idx in PARTICIPANTS_ROWS:
        if row_idx >= len(df):
            break
        row = df.iloc[row_idx]
        name = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
        if not name or name == "nan":
            continue

        participants[name] = {
            "notwendig": safe_bool(row.iloc[1]),
            "optional": safe_bool(row.iloc[2]),
            "anwesend": safe_bool(row.iloc[3]) if safe_int(row.iloc[3], -1) != -1 else False,
            "verzug_min": safe_int(row.iloc[4]),
            "frueher_raus_min": 0,
            "anwesend_min": safe_int(row.iloc[5]),
            "behavior": {
                "konstruktiv":    safe_int(row.iloc[6]),
                "unterbrechung":  safe_int(row.iloc[7]),
                "geringschaetzend": safe_int(row.iloc[9]),
                "hand_gehoben":   safe_int(row.iloc[10]),
            },
        }
        # Anwesend: wenn anwesend_min > 0 → war da
        if participants[name]["anwesend_min"] > 0:
            participants[name]["anwesend"] = True

    # Meeting-Kennzahl: Dauer
    dauer = 0
    for row_idx in range(9, min(20, len(df))):
        row = df.iloc[row_idx]
        label = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
        if "Meetingdauer" in label:
            dauer = safe_int(row.iloc[1])
            break

    return participants, dauer


def main():
    if not EXCEL_PATH.exists():
        print(f"Datei nicht gefunden: {EXCEL_PATH}")
        sys.exit(1)

    xl = pd.ExcelFile(EXCEL_PATH)
    all_participants = set()
    sessions = []

    for sheet_name in xl.sheet_names:
        if sheet_name in SKIP_SHEETS:
            continue
        date_str = parse_date(sheet_name)
        if not date_str:
            print(f"  Übersprungen (kein Datum): {sheet_name}")
            continue

        df = pd.read_excel(EXCEL_PATH, sheet_name=sheet_name, header=None)
        participants, dauer = parse_sheet(df)
        notes = collect_notes(df)

        all_participants.update(participants.keys())

        sessions.append({
            "date": date_str,
            "meeting_metrics": {"dauer_min": dauer},
            "participants": participants,
            "notes": notes,
        })
        print(f"  ✓ {sheet_name} → {date_str} ({len(participants)} Teilnehmer, {dauer} Min)")

    sessions.sort(key=lambda s: s["date"])

    # Teilnehmer in konsistenter Reihenfolge (nach Häufigkeit der Anwesenheit)
    participant_order = sorted(
        all_participants,
        key=lambda p: -sum(1 for s in sessions if p in s["participants"]),
    )

    config = {
        "display_name": "Leitungsmeeting",
        "participants": participant_order,
        "behavior_metrics": [
            {"key": "konstruktiv",      "label": "Konstruktiv"},
            {"key": "unterbrechung",    "label": "Unterbrechung"},
            {"key": "geringschaetzend", "label": "Geringschätzend"},
            {"key": "hand_gehoben",     "label": "Hand gehoben"},
        ],
        "meeting_metrics": [
            {"key": "dauer_min", "label": "Meetingdauer (Min)"},
        ],
        "note_categories": [
            {"key": "organisatorisches", "label": "Organisatorisches"},
            {"key": "soziales",          "label": "Soziales & Emotionales"},
            {"key": "verbesserungen",    "label": "Verbesserungsvorschläge"},
        ],
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_DIR / "project.json", "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    with open(DATA_DIR / "sessions.json", "w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Import abgeschlossen:")
    print(f"   Projekt:      {DATA_DIR}/project.json")
    print(f"   Sessions:     {DATA_DIR}/sessions.json")
    print(f"   Teilnehmer:   {', '.join(participant_order)}")
    print(f"   Meetings:     {len(sessions)}")


if __name__ == "__main__":
    main()
