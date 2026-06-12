import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.analytics import (
    trend, climate_score, climate_status, outlier_meetings, equity,
    archetypes, generate_findings, person_rate_series, participant_card,
)
from app.storage import DEFAULT_CONFIG


def make_config(participants=("Anna", "Ben", "Cleo", "Dora")):
    cfg = dict(DEFAULT_CONFIG)
    cfg["participants"] = list(participants)
    cfg["inactive_participants"] = {}
    return cfg


def make_session(date, behavior_by_person, dauer=60, verzug=None):
    """behavior_by_person: {name: {metric: count}}"""
    verzug = verzug or {}
    return {
        "date": date,
        "meeting_metrics": {"dauer_min": dauer},
        "participants": {
            name: {
                "notwendig": False, "optional": False, "anwesend": True,
                "verzug_min": verzug.get(name, 0), "frueher_raus_min": 0,
                "anwesend_min": dauer - verzug.get(name, 0),
                "behavior": {
                    "konstruktiv": b.get("konstruktiv", 0),
                    "unterbrechung": b.get("unterbrechung", 0),
                    "geringschaetzend": b.get("geringschaetzend", 0),
                    "hand_gehoben": b.get("hand_gehoben", 0),
                },
            }
            for name, b in behavior_by_person.items()
        },
        "notes": {},
    }


def sessions_with_pattern(counts_anna, metric="unterbrechung", dauer=60):
    """Eine Session pro Wert; Anna bekommt die Werte, Ben konstant 1."""
    return [
        make_session(f"2026-01-{i + 1:02d}",
                     {"Anna": {metric: c}, "Ben": {metric: 1}, "Cleo": {}, "Dora": {}},
                     dauer=dauer)
        for i, c in enumerate(counts_anna)
    ]


# ── Trend ──────────────────────────────────────────────────────────────────────

def test_trend_improvement_lower_is_better():
    sessions = sessions_with_pattern([6, 6, 6, 6, 1, 1, 1, 1])
    cfg = make_config()
    series = person_rate_series(sessions, cfg, "Anna", "unterbrechung")
    t = trend(series, "unterbrechung")
    assert t.direction == "verbessert"
    assert t.recent < t.baseline


def test_trend_deterioration_lower_is_better():
    sessions = sessions_with_pattern([1, 1, 1, 1, 6, 6, 6, 6])
    cfg = make_config()
    t = trend(person_rate_series(sessions, cfg, "Anna", "unterbrechung"), "unterbrechung")
    assert t.direction == "verschlechtert"


def test_trend_improvement_higher_is_better():
    sessions = sessions_with_pattern([1, 1, 1, 1, 6, 6, 6, 6], metric="konstruktiv")
    cfg = make_config()
    t = trend(person_rate_series(sessions, cfg, "Anna", "konstruktiv"), "konstruktiv")
    assert t.direction == "verbessert"


def test_trend_stable_below_thresholds():
    # 4 → 5 pro Meeting = +25% aber unter Schwelle bei genauem Blick: rate 4/h vs 5/h,
    # delta_pct = 0.25 (nicht > Schwelle-Grenzfall) — nutze kleinere Änderung
    sessions = sessions_with_pattern([4, 4, 4, 4, 4, 5, 4, 4])
    cfg = make_config()
    t = trend(person_rate_series(sessions, cfg, "Anna", "unterbrechung"), "unterbrechung")
    assert t.direction == "stabil"


def test_trend_noise_guard_small_absolute_change():
    # 0.2/h → 0.4/h ist +100 %, aber absolut < 0.5/h → kein Signal
    sessions = sessions_with_pattern([1, 0, 1, 0, 1, 1, 0, 1], dauer=300)
    cfg = make_config()
    t = trend(person_rate_series(sessions, cfg, "Anna", "unterbrechung"), "unterbrechung")
    assert t.direction == "stabil"


def test_trend_needs_enough_data():
    sessions = sessions_with_pattern([1, 2, 3])
    cfg = make_config()
    assert trend(person_rate_series(sessions, cfg, "Anna", "unterbrechung"), "unterbrechung") is None


# ── Klima-Score ────────────────────────────────────────────────────────────────

def test_climate_score_perfect_meeting():
    cfg = make_config()
    s = make_session("2026-01-01", {
        "Anna": {"konstruktiv": 3, "hand_gehoben": 2},
        "Ben": {"konstruktiv": 2, "hand_gehoben": 1},
        "Cleo": {"konstruktiv": 2}, "Dora": {"konstruktiv": 2},
    })
    score, reasons = climate_score(s, cfg)
    assert score >= 90
    assert any("keine Geringschätzung" in r for r in reasons)


def test_climate_score_bad_meeting():
    cfg = make_config()
    s = make_session("2026-01-01", {
        "Anna": {"unterbrechung": 8, "geringschaetzend": 2},
        "Ben": {"unterbrechung": 6, "geringschaetzend": 1},
        "Cleo": {}, "Dora": {},
    }, verzug={"Anna": 15, "Ben": 10})
    score, _ = climate_score(s, cfg)
    assert score < 45


def test_climate_score_bounds_and_status():
    assert climate_status(85) == ("🟢", "Gut")
    assert climate_status(55) == ("🟡", "Beobachten")
    assert climate_status(20) == ("🔴", "Kritisch")


# ── Ausreißer ──────────────────────────────────────────────────────────────────

def test_outlier_detection():
    cfg = make_config()
    counts = [3, 4, 3, 4, 3, 4, 3, 25]
    sessions = sessions_with_pattern(counts)
    outliers = outlier_meetings(sessions, cfg)
    assert any(o["date"] == "2026-01-08" and o["metric"] == "unterbrechung" for o in outliers)


# ── Equity / Ungleichgewicht ───────────────────────────────────────────────────

def test_equity_flags_dominant_person():
    cfg = make_config()
    sessions = [
        make_session(f"2026-01-{i:02d}", {
            "Anna": {"unterbrechung": 9}, "Ben": {"unterbrechung": 1},
            "Cleo": {"unterbrechung": 1}, "Dora": {"unterbrechung": 1},
        })
        for i in range(1, 5)
    ]
    eq = equity(sessions, cfg, "unterbrechung")
    assert eq["flagged"] == ["Anna"]
    assert eq["shares"]["Anna"] > 0.7


# ── Archetypen ─────────────────────────────────────────────────────────────────

def test_archetype_interrupter_and_driver():
    cfg = make_config()
    sessions = [
        make_session(f"2026-01-{i:02d}", {
            "Anna": {"unterbrechung": 8},
            "Ben": {"konstruktiv": 6, "hand_gehoben": 5, "unterbrechung": 1},
            "Cleo": {"konstruktiv": 1, "hand_gehoben": 1},
            "Dora": {"konstruktiv": 1, "hand_gehoben": 1},
        })
        for i in range(1, 7)
    ]
    tags = archetypes(sessions, cfg)
    assert "🗣️ Unterbricht häufig" in tags["Anna"]
    assert "🧱 Konstruktiver Treiber" in tags["Ben"]


# ── Findings ───────────────────────────────────────────────────────────────────

def test_findings_sorted_by_severity_and_have_evidence():
    cfg = make_config()
    sessions = sessions_with_pattern([1, 1, 1, 1, 6, 6, 6, 6])  # Anna verschlechtert
    findings = generate_findings(sessions, cfg)
    assert findings, "Erwartet mindestens ein Finding"
    assert findings == sorted(findings, key=lambda f: f.severity)
    worst = findings[0]
    assert worst.status_word == "Verschlechtert"
    assert "Anna" in worst.text
    assert worst.evidence.get("dates") and worst.evidence.get("values")


def test_findings_empty_for_few_sessions():
    cfg = make_config()
    assert generate_findings(sessions_with_pattern([1, 2]), cfg) == []


# ── Teilnehmer-Karte ───────────────────────────────────────────────────────────

def test_participant_card_structure():
    cfg = make_config()
    sessions = sessions_with_pattern([6, 6, 6, 6, 1, 1, 1, 1])
    card = participant_card(sessions, cfg, "Anna")
    assert card["attendance"] == 1.0
    by_label = {m.label: m for m in card["metrics"]}
    assert by_label["Unterbrechung"].word == "verbessert"
    assert by_label["Unterbrechung"].arrow == "↓"
