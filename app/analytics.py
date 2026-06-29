"""Regelbasierte Auswertungslogik: Raten, Trends, Klima-Score, Findings.

Reine Funktionen ohne Streamlit-Abhängigkeit. Grundprinzip: nie rohe
Zählwerte vergleichen, immer Raten pro Stunde Anwesenheit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations
from statistics import median

# ── Schwellen & Semantik (zentrale Kalibrierungsstellen) ──────────────────────

TREND_WINDOW = 4            # Meetings im Vergleichsfenster (recent vs. baseline)
TREND_MIN_DELTA_PCT = 0.25  # Mindeständerung relativ
TREND_MIN_DELTA_ABS = 0.5   # Mindeständerung absolut (Ereignisse/h) — Rauschschutz
SLOPE_POINTS = 6            # Punkte für Theil-Sen-Bestätigung
OUTLIER_Z = 2.0             # z-Score-Schwelle für Ausreißer-Meetings
EQUITY_WINDOW = 4           # Fenster für Ungleichgewichts-Analyse
EQUITY_FAIR_FACTOR = 2.0    # Signal ab > Faktor × fairer Anteil
ARCHETYPE_WINDOW = 6        # Fenster für Teilnehmer-Profile
LATE_SHARE = 0.5            # "chronisch verspätet" ab Verspätung in ≥ 50 % der Meetings
LATE_MIN_COUNT = 3          # ... und mindestens so vielen Vorkommen
ZERO_STREAK_MIN = 5         # "positiv stabil" ab so vielen Meetings ohne Vorkommnis
OWNER_SHARE_MIN = 0.5       # "häufig Moderator" ab diesem Anteil der Meetings im Fenster

# Klima-Score: Referenzwerte "ab hier voller Abzug/Bonus"
SCORE_INT_RATE_BAD = 12.0   # Unterbrechungen/h Team
SCORE_GS_RATE_BAD = 3.0     # Geringschätzungen/h Team
SCORE_KON_RATE_GOOD = 8.0   # Konstruktiv/h Team
SCORE_VERZUG_BAD = 10.0     # Ø Verzug (Min) der Anwesenden
SCORE_GOOD = 70             # Ampel-Grenzen
SCORE_WATCH = 45

LOWER_IS_BETTER = {"unterbrechung", "geringschaetzend"}
HIGHER_IS_BETTER = {"konstruktiv", "hand_gehoben"}


def is_active(config: dict, name: str, for_date: str) -> bool:
    inactive = config.get("inactive_participants", {})
    if name not in inactive:
        return True
    return for_date <= inactive[name]


def is_behavioral(session: dict) -> bool:
    """False wenn die Session als 'Nur Anwesenheit' markiert ist."""
    return session.get("behavioral_data", True) is not False


def fmt_de(x: float, digits: int = 1) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


def fmt_date(date_str: str) -> str:
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")


def metric_label(config: dict, key: str) -> str:
    for m in config.get("behavior_metrics", []):
        if m["key"] == key:
            return m["label"]
    return key


# ── Raten-Serien ───────────────────────────────────────────────────────────────

def person_rate_series(sessions: list, config: dict, person: str, metric: str) -> list[tuple[str, float]]:
    """(date, Ereignisse pro Stunde Anwesenheit) — nur gemessene Meetings mit Anwesenheit."""
    out = []
    for s in sessions:
        if not is_behavioral(s):
            continue
        if not is_active(config, person, s["date"]):
            continue
        p = s["participants"].get(person)
        if not p or not p.get("anwesend"):
            continue
        mins = p.get("anwesend_min", 0) or s["meeting_metrics"].get("dauer_min", 0)
        if not mins:
            continue
        out.append((s["date"], p["behavior"].get(metric, 0) / mins * 60))
    return out


def team_rate_series(sessions: list, config: dict, metric: str) -> list[tuple[str, float]]:
    """(date, Team-Ereignisse pro Meeting-Stunde) — nur gemessene Meetings."""
    out = []
    for s in sessions:
        if not is_behavioral(s):
            continue
        dauer = s["meeting_metrics"].get("dauer_min", 0)
        if not dauer:
            continue
        total = sum(
            p["behavior"].get(metric, 0)
            for name, p in s["participants"].items()
            if is_active(config, name, s["date"])
        )
        out.append((s["date"], total / dauer * 60))
    return out


# ── Trend-Erkennung ────────────────────────────────────────────────────────────

@dataclass
class TrendResult:
    direction: str          # "verbessert" | "verschlechtert" | "stabil"
    confidence: str         # "klar" | "Tendenz" | ""
    recent: float
    baseline: float
    delta_pct: float
    n_points: int


def _theil_sen_slope(values: list[float]) -> float:
    pts = list(enumerate(values))
    slopes = [(y2 - y1) / (x2 - x1) for (x1, y1), (x2, y2) in combinations(pts, 2) if x2 != x1]
    return median(slopes) if slopes else 0.0


def trend(series: list[tuple[str, float]], metric: str, window: int = TREND_WINDOW) -> TrendResult | None:
    """Vergleich der letzten `window` Werte gegen die `window` davor (Fallback: alle früheren)."""
    values = [v for _, v in series]
    if len(values) < window + 2:
        return None
    recent_vals = values[-window:]
    base_vals = values[-2 * window:-window] if len(values) >= 2 * window else values[:-window]
    recent = sum(recent_vals) / len(recent_vals)
    baseline = sum(base_vals) / len(base_vals)
    delta = recent - baseline
    delta_pct = delta / baseline if baseline else (1.0 if delta > 0 else 0.0)

    if abs(delta_pct) < TREND_MIN_DELTA_PCT or abs(delta) < TREND_MIN_DELTA_ABS:
        return TrendResult("stabil", "", recent, baseline, delta_pct, len(values))

    if metric in LOWER_IS_BETTER:
        direction = "verbessert" if delta < 0 else "verschlechtert"
    elif metric in HIGHER_IS_BETTER:
        direction = "verbessert" if delta > 0 else "verschlechtert"
    else:
        direction = "verändert"

    slope = _theil_sen_slope(values[-SLOPE_POINTS:])
    confidence = "klar" if (slope > 0) == (delta > 0) and slope != 0 else "Tendenz"
    return TrendResult(direction, confidence, recent, baseline, delta_pct, len(values))


# ── Klima-Score ────────────────────────────────────────────────────────────────

def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def climate_score(session: dict, config: dict) -> tuple[int | None, list[str]]:
    """0–100 plus menschenlesbare Begründungen. None wenn keine Verhaltensdaten."""
    if not is_behavioral(session):
        return None, ["Keine Verhaltensdaten erfasst (nur Anwesenheit)"]
    dauer = session["meeting_metrics"].get("dauer_min", 0)
    pp = {n: p for n, p in session["participants"].items() if is_active(config, n, session["date"])}
    present = [p for p in pp.values() if p.get("anwesend")]
    reasons = []
    if not dauer or not pp:
        return 50, ["Unvollständige Daten (Dauer oder Teilnehmer fehlen)"]

    int_rate = sum(p["behavior"].get("unterbrechung", 0) for p in pp.values()) / dauer * 60
    gs_rate = sum(p["behavior"].get("geringschaetzend", 0) for p in pp.values()) / dauer * 60
    kon_rate = sum(p["behavior"].get("konstruktiv", 0) for p in pp.values()) / dauer * 60
    att = len(present) / len(pp)
    avg_verzug = sum(p.get("verzug_min", 0) for p in present) / len(present) if present else 0

    score = 100.0
    score -= 25 * _clip(int_rate / SCORE_INT_RATE_BAD)
    score -= 30 * _clip(gs_rate / SCORE_GS_RATE_BAD)
    score -= 15 * (1 - att)
    score -= 10 * _clip(avg_verzug / SCORE_VERZUG_BAD)
    score += 20 * _clip(kon_rate / SCORE_KON_RATE_GOOD) - 10

    reasons.append(f"Unterbrechungsrate {fmt_de(int_rate)}/h")
    if gs_rate > 0:
        reasons.append(f"Geringschätzung {fmt_de(gs_rate)}/h")
    else:
        reasons.append("keine Geringschätzung")
    reasons.append(f"Konstruktiv-Rate {fmt_de(kon_rate)}/h")
    reasons.append(f"Anwesenheit {att:.0%}")
    if avg_verzug >= 1:
        reasons.append(f"Ø Verzug {fmt_de(avg_verzug, 0)} Min")
    return round(_clip(score, 0, 100)), reasons


def climate_status(score: float) -> tuple[str, str]:
    """Ampel als Icon + Wort (Farbe nie allein)."""
    if score >= SCORE_GOOD:
        return "🟢", "Gut"
    if score >= SCORE_WATCH:
        return "🟡", "Beobachten"
    return "🔴", "Kritisch"


def climate_series(sessions: list, config: dict) -> list[tuple[str, int | None]]:
    """None für partielle Sessions — Plotly zeigt Lücke im Chart."""
    return [(s["date"], climate_score(s, config)[0]) for s in sessions]


# ── Rollen-Erkennung ──────────────────────────────────────────────────────────

def person_roles(sessions: list, window: int = ARCHETYPE_WINDOW) -> dict[str, list[str]]:
    """Welche Rollen trägt eine Person häufig im Fenster?
    Gibt dict {person: ['🎙️ Moderation', '📋 Protokoll']} zurück."""
    recent = sessions[-window:]
    n = len(recent)
    if not n:
        return {}
    owner_count: dict[str, int] = {}
    proto_count: dict[str, int] = {}
    for s in recent:
        o = s.get("meeting_owner", "")
        p = s.get("protokollant", "")
        if o:
            owner_count[o] = owner_count.get(o, 0) + 1
        if p:
            proto_count[p] = proto_count.get(p, 0) + 1
    roles: dict[str, list[str]] = {}
    for person, cnt in owner_count.items():
        if cnt / n >= OWNER_SHARE_MIN:
            roles.setdefault(person, []).append("🎙️ Moderation")
    for person, cnt in proto_count.items():
        if cnt / n >= OWNER_SHARE_MIN:
            roles.setdefault(person, []).append("📋 Protokoll")
    return roles


# ── Ausreißer, Ungleichgewicht, Archetypen ─────────────────────────────────────

def outlier_meetings(sessions: list, config: dict) -> list[dict]:
    """Meetings, deren Team-Rate ≥ OUTLIER_Z Standardabweichungen von der Historie abweicht."""
    out = []
    for m in (bm["key"] for bm in config.get("behavior_metrics", [])):
        series = team_rate_series(sessions, config, m)
        if len(series) < 5:
            continue
        values = [v for _, v in series]
        mean = sum(values) / len(values)
        var = sum((v - mean) ** 2 for v in values) / len(values)
        std = var ** 0.5
        if std == 0:
            continue
        for date_str, v in series:
            z = (v - mean) / std
            if abs(z) >= OUTLIER_Z:
                out.append({"date": date_str, "metric": m, "rate": v, "typical": mean, "z": z})
    return out


def equity(sessions: list, config: dict, metric: str, window: int = EQUITY_WINDOW) -> dict:
    """Anteile pro Person im Fenster; flagged = Personen über Faktor × fairem Anteil."""
    recent = sessions[-window:]
    counts: dict[str, int] = {}
    persons = set()
    for s in recent:
        for name, p in s["participants"].items():
            if not is_active(config, name, s["date"]) or not p.get("anwesend"):
                continue
            persons.add(name)
            counts[name] = counts.get(name, 0) + p["behavior"].get(metric, 0)
    total = sum(counts.values())
    if not total or len(persons) < 3:
        return {"shares": {}, "flagged": [], "fair": 0.0, "total": total}
    fair = 1 / len(persons)
    shares = {p: c / total for p, c in counts.items()}
    flagged = [p for p, sh in shares.items() if sh > EQUITY_FAIR_FACTOR * fair]
    return {"shares": shares, "flagged": flagged, "fair": fair, "total": total, "n_persons": len(persons)}


def archetypes(sessions: list, config: dict, window: int = ARCHETYPE_WINDOW) -> dict[str, list[str]]:
    """Regelbasierte Profil-Tags pro Person über das jüngste Fenster."""
    recent = sessions[-window:]
    if not recent:
        return {}
    persons = [p for p in config.get("participants", [])
               if any(is_active(config, p, s["date"]) for s in recent)]
    rates: dict[str, dict[str, float]] = {}
    gs_meetings: dict[str, int] = {}
    for person in persons:
        rates[person] = {}
        for m in ("konstruktiv", "unterbrechung", "geringschaetzend", "hand_gehoben"):
            series = person_rate_series(recent, config, person, m)
            rates[person][m] = sum(v for _, v in series) / len(series) if series else 0.0
        gs_meetings[person] = sum(
            1 for s in recent
            if s["participants"].get(person, {}).get("behavior", {}).get("geringschaetzend", 0) > 0
        )

    def team_median(metric):
        vals = sorted(rates[p][metric] for p in persons)
        return median(vals) if vals else 0.0

    eq = equity(recent, config, "unterbrechung", window=window)
    roles = person_roles(recent, window=window)
    tags: dict[str, list[str]] = {p: [] for p in persons}
    kon_max = max((rates[p]["konstruktiv"] for p in persons), default=0)
    hand_med = team_median("hand_gehoben")
    medians = {m: team_median(m) for m in ("konstruktiv", "unterbrechung", "hand_gehoben")}

    for p in persons:
        r = rates[p]
        # Rollen zuerst — damit sie oben in der Karte erscheinen
        tags[p].extend(roles.get(p, []))
        if p in eq.get("flagged", []) and "🎙️ Moderation" not in roles.get(p, []):
            tags[p].append("🗣️ Unterbricht häufig")
        wm = r["hand_gehoben"] + r["unterbrechung"]
        disziplin = r["hand_gehoben"] / wm if wm else 1.0
        if r["konstruktiv"] == kon_max and kon_max > 0 and disziplin >= 0.7:
            tags[p].append("🧱 Konstruktiver Treiber")
        if hand_med > 0 and r["hand_gehoben"] >= 1.5 * hand_med:
            tags[p].append("✋ Meldet sich")
        if all(r[m] < 0.25 * medians[m] for m in medians if medians[m] > 0) and any(
                medians[m] > 0 for m in medians):
            tags[p].append("🤫 Stiller Beobachter")
        if gs_meetings[p] >= 3:
            tags[p].append("⚠️ Geringschätzung auffällig")
    return tags


# ── Pro-Meeting-Kennzahlen (aus app.py hierher verschoben) ─────────────────────

def computed_metrics(session: dict, config: dict) -> dict:
    dauer = session["meeting_metrics"].get("dauer_min", 0)
    pp = session["participants"]
    total_int = sum(p["behavior"].get("unterbrechung", 0) for p in pp.values())
    total_min = sum(p.get("anwesend_min", 0) for p in pp.values())
    req = sum(1 for p in pp.values() if p.get("notwendig"))
    max_min = req * dauer if req and dauer else 0
    att = total_min / max_min if max_min else None
    interval = dauer / total_int if dauer and total_int else None
    blocked = total_int / dauer if dauer else None
    return {
        "Unterbrechungen":        total_int,
        "Unterbrech. alle (Min)": round(interval, 1) if interval else "—",
        "Freie Rede blockiert":   f"{blocked:.1%}" if blocked is not None else "—",
        "Anwesenheit":            f"{att:.1%}" if att is not None else "—",
        "Geringschätzung":        sum(p["behavior"].get("geringschaetzend", 0) for p in pp.values()),
        "Hand gehoben":           sum(p["behavior"].get("hand_gehoben", 0) for p in pp.values()),
    }


# ── Findings ───────────────────────────────────────────────────────────────────

@dataclass
class Finding:
    icon: str
    status_word: str
    text: str
    severity: int                       # kleiner = wichtiger
    evidence: dict = field(default_factory=dict)  # dates, values, label, split_idx


def _evidence(series: list[tuple[str, float]], label: str, window: int = TREND_WINDOW) -> dict:
    return {
        "dates": [d for d, _ in series],
        "values": [v for _, v in series],
        "label": label,
        "split_idx": max(len(series) - window, 0),
    }


def generate_findings(sessions: list, config: dict) -> list[Finding]:
    findings: list[Finding] = []
    if len(sessions) < 3:
        return findings
    bm_keys = [m["key"] for m in config.get("behavior_metrics", [])]
    persons = [p for p in config.get("participants", [])
               if any(is_active(config, p, s["date"]) for s in sessions[-TREND_WINDOW:])]

    # 1) Personen-Trends
    for person in persons:
        for m in bm_keys:
            series = person_rate_series(sessions, config, person, m)
            t = trend(series, m)
            if not t or t.direction == "stabil":
                continue
            lbl = metric_label(config, m)
            verlauf = "Klarer Trend" if t.confidence == "klar" else "Tendenz"
            up = t.recent > t.baseline
            if t.baseline == 0:
                change = (f"neu aufgetreten: {fmt_de(t.recent)} pro Stunde "
                          f"(zuvor keine, letzte {TREND_WINDOW} Meetings)")
            elif t.recent == 0:
                change = (f"auf null gefallen (zuvor {fmt_de(t.baseline)} pro Stunde, "
                          f"letzte {TREND_WINDOW} Meetings)")
            else:
                change = (f"{'gestiegen' if up else 'gefallen'} um {abs(t.delta_pct):.0%} "
                          f"({fmt_de(t.baseline)} → {fmt_de(t.recent)} pro Stunde, "
                          f"letzte {TREND_WINDOW} Meetings)")
            if t.direction == "verbessert":
                findings.append(Finding(
                    "📉" if not up else "📈", "Verbessert",
                    f"{person}: {lbl} {change}. {verlauf}.",
                    severity=4,
                    evidence=_evidence(series, f"{person} — {lbl}/h"),
                ))
            elif t.direction == "verschlechtert":
                findings.append(Finding(
                    "📈" if up else "📉", "Verschlechtert",
                    f"{person}: {lbl} {change}. {verlauf}.",
                    severity=0,
                    evidence=_evidence(series, f"{person} — {lbl}/h"),
                ))

    # 2) Team-Trends
    for m in bm_keys:
        series = team_rate_series(sessions, config, m)
        t = trend(series, m)
        if not t or t.direction == "stabil":
            continue
        lbl = metric_label(config, m)
        word = "Verbessert" if t.direction == "verbessert" else "Verschlechtert"
        sev = 4 if t.direction == "verbessert" else 0
        if t.baseline == 0:
            change = (f"neu aufgetreten: {fmt_de(t.recent)} pro Meeting-Stunde "
                      f"(zuvor keine, letzte {TREND_WINDOW} Meetings)")
        else:
            richt = "gefallen" if t.recent < t.baseline else "gestiegen"
            change = (f"{richt} von {fmt_de(t.baseline)} auf {fmt_de(t.recent)} "
                      f"pro Meeting-Stunde ({t.delta_pct:+.0%}, letzte {TREND_WINDOW} Meetings)")
        findings.append(Finding(
            "📉" if t.recent < t.baseline else "📈", word,
            f"Team gesamt: {lbl} {change}.",
            severity=sev,
            evidence=_evidence(series, f"Team — {lbl}/h"),
        ))

    # 3) Ausreißer-Meetings (nur die jüngsten 6 Meetings melden)
    recent_dates = {s["date"] for s in sessions[-6:]}
    for o in outlier_meetings(sessions, config):
        if o["date"] not in recent_dates or o["z"] < 0:
            continue
        lbl = metric_label(config, o["metric"])
        series = team_rate_series(sessions, config, o["metric"])
        findings.append(Finding(
            "⚠️", "Auffällig",
            f"Das Meeting vom {fmt_date(o['date'])} war ein Ausreißer: {lbl} bei "
            f"{fmt_de(o['rate'])}/h (üblich: ~{fmt_de(o['typical'])}/h). Notizen dieses Tages prüfen.",
            severity=1,
            evidence=_evidence(series, f"Team — {lbl}/h"),
        ))

    # 4) Ungleichgewicht bei Unterbrechungen
    if "unterbrechung" in bm_keys:
        roles = person_roles(sessions)
        eq = equity(sessions, config, "unterbrechung")
        # Moderatoren aus dem Flagging herausnehmen — ihr Unterbrechen ist strukturbedingt
        flagged_non_mod = [p for p in eq["flagged"] if "🎙️ Moderation" not in roles.get(p, [])]
        flagged_mod = [p for p in eq["flagged"] if "🎙️ Moderation" in roles.get(p, [])]
        if flagged_non_mod:
            share_sum = sum(eq["shares"][p] for p in flagged_non_mod)
            n_f = len(flagged_non_mod)
            verb = "verursacht" if n_f == 1 else "verursachen"
            mod_note = (f" ({', '.join(flagged_mod)} als Moderation herausgerechnet)"
                        if flagged_mod else "")
            findings.append(Finding(
                "⚖️", "Ungleichgewicht",
                f"{n_f} von {eq['n_persons']} Personen "
                f"({', '.join(sorted(flagged_non_mod))}) {verb} {share_sum:.0%} aller "
                f"Unterbrechungen der letzten {EQUITY_WINDOW} Meetings "
                f"(fairer Anteil: {eq['fair'] * n_f:.0%}){mod_note}.",
                severity=2,
            ))
        elif flagged_mod:
            # Nur Moderatoren auffällig — als Hinweis, nicht als Problem
            share_sum = sum(eq["shares"][p] for p in flagged_mod)
            findings.append(Finding(
                "ℹ️", "Hinweis",
                f"{', '.join(sorted(flagged_mod))} {('unterbricht' if len(flagged_mod)==1 else 'unterbrechen')} "
                f"häufig ({share_sum:.0%} aller Unterbrechungen), was der Moderationsrolle entspricht.",
                severity=5,
            ))

    # 5) Chronische Verspätung
    for person in persons:
        attended = [s for s in sessions[-8:]
                    if s["participants"].get(person, {}).get("anwesend")
                    and is_active(config, person, s["date"])]
        late = [s["participants"][person].get("verzug_min", 0) for s in attended
                if s["participants"][person].get("verzug_min", 0) > 0]
        if len(attended) >= LATE_MIN_COUNT and len(late) >= max(LATE_MIN_COUNT, LATE_SHARE * len(attended)):
            findings.append(Finding(
                "⏰", "Pünktlichkeit",
                f"{person} kam in {len(late)} der letzten {len(attended)} besuchten Meetings "
                f"verspätet (Ø {fmt_de(sum(late) / len(late), 0)} Min).",
                severity=3,
            ))

    # 6) Positiv stabil: Geringschätzung bei null
    if "geringschaetzend" in bm_keys and len(sessions) >= ZERO_STREAK_MIN:
        streak = 0
        for s in reversed(sessions):
            total = sum(p["behavior"].get("geringschaetzend", 0) for p in s["participants"].values())
            if total == 0:
                streak += 1
            else:
                break
        if streak >= ZERO_STREAK_MIN:
            findings.append(Finding(
                "✅", "Positiv stabil",
                f"Geringschätzende Äußerungen seit {streak} Meetings bei null.",
                severity=5,
            ))

    findings.sort(key=lambda f: f.severity)
    return findings


# ── Teilnehmer-Karten (Zone C) ─────────────────────────────────────────────────

@dataclass
class MetricStatus:
    label: str
    arrow: str          # ↑ ↓ → —
    word: str
    rate: float | None
    delta_pct: float | None


def participant_card(sessions: list, config: dict, person: str) -> dict:
    """Daten für eine Teilnehmer-Karte: Trend je Metrik + Anwesenheit + Verzug."""
    metrics: list[MetricStatus] = []
    for m in config.get("behavior_metrics", []):
        series = person_rate_series(sessions, config, person, m["key"])
        if not series:
            metrics.append(MetricStatus(m["label"], "—", "keine Daten", None, None))
            continue
        recent_vals = [v for _, v in series[-TREND_WINDOW:]]
        rate = sum(recent_vals) / len(recent_vals)
        t = trend(series, m["key"])
        if not t or t.direction == "stabil":
            metrics.append(MetricStatus(m["label"], "→", "stabil", rate, t.delta_pct if t else None))
        else:
            up = t.recent > t.baseline
            metrics.append(MetricStatus(m["label"], "↑" if up else "↓", t.direction, rate, t.delta_pct))

    attended, total, verzug = 0, 0, []
    for s in sessions:
        if not is_active(config, person, s["date"]):
            continue
        total += 1
        p = s["participants"].get(person, {})
        if p.get("anwesend"):
            attended += 1
            verzug.append(p.get("verzug_min", 0))
    return {
        "person": person,
        "metrics": metrics,
        "attendance": attended / total if total else None,
        "avg_verzug": sum(verzug) / len(verzug) if verzug else 0,
        "tags": archetypes(sessions, config).get(person, []),
    }
