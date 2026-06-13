import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date, datetime
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from app.storage import (
    list_projects, load_project, save_project,
    load_sessions, save_session, delete_session,
    load_app_state, save_app_state, person_colors,
    DEFAULT_CONFIG,
)
from app.analytics import (
    computed_metrics, is_active, climate_score, climate_status,
    generate_findings, fmt_de,
)
from app.insights_ui import page_insights

st.set_page_config(page_title="Meeting Social Tracking", page_icon="📊", layout="wide")

TEAL = ["#59B2A5", "#3a8a7e", "#246b61", "#a8d8d2", "#7a9e9a", "#e8f6f4"]

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&display=swap');

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif !important; }

[data-testid="stSidebar"] { background-color: #f2f7f6 !important; border-right: 1px solid #d4e8e5; }
[data-testid="stSidebar"] .stButton > button {
    background: transparent; border: none; color: #4a6b67;
    text-align: left; font-weight: 400; border-radius: 8px;
    transition: background 0.15s, color 0.15s;
}
[data-testid="stSidebar"] .stButton > button:hover { background: #e8f6f4 !important; color: #246b61 !important; }

[data-testid="metric-container"] {
    background: white; border: 1px solid #d4e8e5; border-radius: 12px;
    padding: 0.75rem 1rem; box-shadow: 0 1px 3px rgba(89,178,165,0.08);
}
[data-testid="metric-container"] label { color: #4a6b67 !important; font-size: 0.8rem !important; font-weight: 500 !important; }
[data-testid="metric-container"] [data-testid="stMetricValue"] {
    color: #1a2e2c !important; font-size: 1.5rem !important;
    font-weight: 600 !important; font-family: 'DM Mono', monospace !important;
}

.grid-header {
    background: #e8f6f4; color: #246b61; font-weight: 600;
    font-size: 0.78rem; padding: 5px 4px; border-radius: 6px;
    text-align: center; margin-bottom: 4px;
}
.grid-name { color: #1a2e2c; font-weight: 500; font-size: 0.95rem; line-height: 36px; }
.grid-name-inactive { color: #7a9e9a; font-size: 0.85rem; line-height: 36px; font-style: italic; }
.counter-val {
    text-align: center; font-size: 1.2rem; font-weight: 600;
    color: #1a2e2c; font-family: 'DM Mono', monospace; line-height: 36px;
}
hr { border-color: #eaf3f1 !important; }
</style>
""", unsafe_allow_html=True)

# ── Session state ──────────────────────────────────────────────────────────────

if "project" not in st.session_state:
    projects_now = list_projects()
    last = load_app_state().get("last_project")
    if last in projects_now:
        st.session_state.project = last
    elif len(projects_now) == 1:
        st.session_state.project = projects_now[0]
    else:
        st.session_state.project = None

for k, v in [("page", "home"), ("confirm_delete", None), ("detail_date", None)]:
    if k not in st.session_state:
        st.session_state[k] = v

# ── Helpers ────────────────────────────────────────────────────────────────────

def get_config() -> dict:
    return load_project(st.session_state.project) if st.session_state.project else {}

# ── Grid / auto-save callbacks ─────────────────────────────────────────────────

def _autosave():
    if not st.session_state.get("meeting_started"):
        return
    project = st.session_state.get("project")
    if not project:
        return
    config = load_project(project)
    date_str = st.session_state.get("grid_date", str(date.today()))
    dauer = st.session_state.get("grid_dauer", 0)

    pp_data = {}
    for p in config.get("participants", []):
        if not is_active(config, p, date_str):
            continue
        anw = st.session_state.grid_anwesend.get(p, False)
        vz = st.session_state.grid_verzug.get(p, 0)
        pp_data[p] = {
            "notwendig": False, "optional": False,
            "anwesend": anw, "verzug_min": vz, "frueher_raus_min": 0,
            "anwesend_min": max(dauer - vz, 0) if anw and dauer else 0,
            "behavior": dict(st.session_state.grid_counters.get(p, {})),
        }

    save_session(project, {
        "date": date_str,
        "meeting_metrics": {"dauer_min": dauer},
        "participants": pp_data,
        "notes": dict(st.session_state.get("grid_notes", {})),
        "meeting_owner": st.session_state.get("grid_owner", ""),
        "protokollant": st.session_state.get("grid_protokollant", ""),
    })


def _inc(p, m):
    st.session_state.grid_counters[p][m] = st.session_state.grid_counters[p].get(m, 0) + 1
    _autosave()


def _dec(p, m):
    v = st.session_state.grid_counters[p].get(m, 0)
    if v > 0:
        st.session_state.grid_counters[p][m] = v - 1
    _autosave()


def _make_inc(p, m): return lambda: _inc(p, m)
def _make_dec(p, m): return lambda: _dec(p, m)


def _toggle_anw(p):
    st.session_state.grid_anwesend[p] = st.session_state[f"anw_{p}"]
    _autosave()


def _update_verzug(p):
    st.session_state.grid_verzug[p] = st.session_state[f"vz_{p}"]
    _autosave()


def _update_dauer():
    st.session_state.grid_dauer = st.session_state["dauer_input"]
    _autosave()


def _init_grid(config: dict, date_str: str):
    if (st.session_state.get("grid_date") == date_str
            and st.session_state.get("grid_project") == st.session_state.project):
        return
    sessions = load_sessions(st.session_state.project)
    existing = next((s for s in sessions if s["date"] == date_str), None)
    bm = config.get("behavior_metrics", [])
    counters, anwesend, verzug, notes = {}, {}, {}, {}

    for p in config.get("participants", []):
        ep = existing["participants"].get(p, {}) if existing else {}
        counters[p] = {m["key"]: ep.get("behavior", {}).get(m["key"], 0) for m in bm}
        anwesend[p] = ep.get("anwesend", False)
        verzug[p] = ep.get("verzug_min", 0)

    for n in config.get("note_categories", []):
        notes[n["key"]] = existing.get("notes", {}).get(n["key"], "") if existing else ""

    st.session_state.grid_counters = counters
    st.session_state.grid_anwesend = anwesend
    st.session_state.grid_verzug = verzug
    st.session_state.grid_notes = notes
    st.session_state.grid_date = date_str
    st.session_state.grid_project = st.session_state.project
    st.session_state.grid_dauer = existing["meeting_metrics"].get("dauer_min", 60) if existing else 60
    st.session_state.grid_owner = existing.get("meeting_owner", "") if existing else ""
    st.session_state.grid_protokollant = existing.get("protokollant", "") if existing else ""
    if existing:
        st.session_state.meeting_started = True

# ── Sidebar ────────────────────────────────────────────────────────────────────

def _set_page(p): st.session_state.page = p


with st.sidebar:
    st.image(str(Path(__file__).parent / "assets" / "logo.webp"), width=160)
    st.markdown(
        "<p style='margin:-6px 0 10px 2px; font-size:0.72rem; "
        "color:#4a6b67; letter-spacing:0.04em;'>Meeting Social Tracking</p>",
        unsafe_allow_html=True,
    )
    projects = list_projects()

    if projects:
        idx = 0
        if st.session_state.project in projects:
            idx = projects.index(st.session_state.project) + 1
        sel = st.selectbox("Projekt", ["— wählen —"] + projects,
                           index=idx, label_visibility="collapsed")
        if sel != "— wählen —" and sel != st.session_state.project:
            st.session_state.project = sel
            st.session_state.page = "home"
            save_app_state({"last_project": sel})
            st.rerun()
    else:
        st.caption("Noch kein Projekt.")

    st.divider()

    if st.session_state.project:
        for label, pg in [
            ("🏠  Start", "home"),
            ("⚡  Meeting erfassen", "capture"),
            ("💡  Insights", "insights"),
            ("📈  Auswertung", "stats"),
        ]:
            st.button(label, use_container_width=True, on_click=_set_page, args=(pg,))
        st.divider()
        st.button("⚙️  Einstellungen", use_container_width=True, on_click=_set_page, args=("config",))

    st.button("🆕  Neues Projekt", use_container_width=True, on_click=_set_page, args=("new_project",))

# ── Pages ──────────────────────────────────────────────────────────────────────

def page_home():
    config = get_config()
    if not config:
        st.title("Meeting Social Tracking")
        st.markdown("Wähle links ein Projekt oder lege ein neues an.")
        return

    sessions = load_sessions(st.session_state.project)
    st.title(config.get("display_name", st.session_state.project))

    if st.button("⚡  Meeting starten", type="primary", use_container_width=True):
        st.session_state.page = "capture"
        st.rerun()

    if not sessions:
        st.info("Noch keine Meetings erfasst — oben starten.")
        return

    # Kompaktstatus: letztes Meeting + wichtigste Befunde
    last = sessions[-1]
    score, _ = climate_score(last, config)
    icon, word = climate_status(score)
    last_label = datetime.strptime(last["date"], "%Y-%m-%d").strftime("%d.%m.%Y")
    st.markdown(f"{icon} **{word}** — Klima-Score {score}/100 im letzten Meeting "
                f"({last_label}).")
    if len(sessions) >= 3:
        for f in generate_findings(sessions, config)[:2]:
            st.markdown(f"{f.icon} **{f.status_word}** — {f.text}")
        st.caption("Alle Befunde mit Belegen unter 💡 Insights.")

    st.divider()
    st.subheader("Meetings")

    for s in reversed(sessions):
        date_label = datetime.strptime(s["date"], "%Y-%m-%d").strftime("%d.%m.%Y")
        dauer = s["meeting_metrics"].get("dauer_min", "?")
        present = sum(1 for p in s["participants"].values() if p.get("anwesend"))
        total = len(s["participants"])
        cm_s = computed_metrics(s, config)

        c1, c2, c3, c4, c5, c_open = st.columns([2, 1.2, 1.2, 1.5, 1.5, 1.2])
        c1.markdown(f"**{date_label}**")
        c2.markdown(f"⏱ {dauer} Min")
        c3.markdown(f"👥 {present}/{total}")
        c4.markdown(f"🔔 {cm_s['Unterbrechungen']}")
        c5.markdown(f"✋ {cm_s['Hand gehoben']}")
        if c_open.button("Öffnen →", key=f"open_{s['date']}"):
            st.session_state.detail_date = s["date"]
            st.session_state.page = "meeting_detail"
            st.rerun()

        st.markdown('<hr style="margin:3px 0;">', unsafe_allow_html=True)


def _save_detail_notes(date_str: str):
    sessions = load_sessions(st.session_state.project)
    s = next((x for x in sessions if x["date"] == date_str), None)
    if not s:
        return
    for n in get_config().get("note_categories", []):
        key = f"detail_note_{n['key']}"
        if key in st.session_state:
            s.setdefault("notes", {})[n["key"]] = st.session_state[key]
    save_session(st.session_state.project, s)
    st.session_state.detail_notes_saved = datetime.now().strftime("%H:%M")


def page_meeting_detail():
    config = get_config()
    date_str = st.session_state.get("detail_date")
    sessions = load_sessions(st.session_state.project) if st.session_state.project else []
    s = next((x for x in sessions if x["date"] == date_str), None)

    if not config or not s:
        st.warning("Meeting nicht gefunden.")
        if st.button("← Zur Startseite"):
            st.session_state.page = "home"
            st.rerun()
        return

    if st.button("←  Start"):
        st.session_state.page = "home"
        st.rerun()

    st.title(f"Meeting vom {datetime.strptime(date_str, '%Y-%m-%d').strftime('%d.%m.%Y')}")

    dauer = s["meeting_metrics"].get("dauer_min", 0)
    present = sum(1 for p in s["participants"].values() if p.get("anwesend"))
    total = len(s["participants"])
    score, reasons = climate_score(s, config)
    icon, word = climate_status(score)

    k1, k2, k3 = st.columns(3)
    k1.metric("Dauer", f"{dauer} Min")
    k2.metric("Anwesend", f"{present}/{total}")
    k3.metric("Klima-Score", f"{score}/100")
    st.markdown(f"{icon} **{word}** — {' · '.join(reasons)}")

    owner = s.get("meeting_owner", "")
    proto = s.get("protokollant", "")
    if owner or proto:
        parts = []
        if owner:
            parts.append(f"🎙️ Moderation: **{owner}**")
        if proto:
            parts.append(f"📋 Protokoll: **{proto}**")
        st.markdown("  ·  ".join(parts))

    # Einordnung gegen die letzten Meetings davor
    st.divider()
    st.subheader("Einordnung")
    idx = sessions.index(s)
    prev = sessions[max(0, idx - 3):idx]
    if not prev:
        st.caption("Erstes Meeting — noch kein Vergleich möglich.")
    else:
        bm = config.get("behavior_metrics", [])
        for m in bm:
            def _total(sess):
                return sum(
                    p["behavior"].get(m["key"], 0)
                    for name, p in sess["participants"].items()
                    if is_active(config, name, sess["date"])
                )
            val = _total(s)
            avg = sum(_total(x) for x in prev) / len(prev)
            diff = val - avg
            if abs(diff) < max(1, 0.2 * avg):
                arrow, w = "→", "Stabil"
            elif diff > 0:
                arrow, w = "▲", "Erhöht"
            else:
                arrow, w = "▼", "Gesenkt"
            st.markdown(f"{arrow} **{w}** — {val} × {m['label']} "
                        f"(Schnitt der letzten {len(prev)} Meetings: {fmt_de(avg)})")

    # Verhalten pro Person
    st.divider()
    st.subheader("Verhalten pro Person")
    bm = config.get("behavior_metrics", [])
    rows = []
    for name, p in s["participants"].items():
        if not is_active(config, name, date_str):
            continue
        row = {"Teilnehmer": name,
               "Anwesend": "✓" if p.get("anwesend") else "—",
               "Verzug (Min)": p.get("verzug_min", 0)}
        for m in bm:
            row[m["label"]] = p["behavior"].get(m["key"], 0)
        rows.append(row)
    st.dataframe(pd.DataFrame(rows).set_index("Teilnehmer"), use_container_width=True)

    # Notizen — werden bei jeder Änderung sofort gespeichert
    st.divider()
    st.subheader("📝 Notizen")
    for n in config.get("note_categories", []):
        st.text_area(n["label"], value=s.get("notes", {}).get(n["key"], ""),
                     key=f"detail_note_{n['key']}", height=90,
                     on_change=_save_detail_notes, args=(date_str,))
    if st.session_state.get("detail_notes_saved"):
        st.caption(f"Gespeichert um {st.session_state.detail_notes_saved} ✓")

    # Löschen
    st.divider()
    if st.session_state.confirm_delete == date_str:
        st.warning("Dieses Meeting endgültig löschen?")
        c1, c2 = st.columns(2)
        if c1.button("⚠️ Ja, löschen", type="primary"):
            delete_session(st.session_state.project, date_str)
            st.session_state.confirm_delete = None
            st.session_state.page = "home"
            st.rerun()
        if c2.button("Abbrechen"):
            st.session_state.confirm_delete = None
            st.rerun()
    else:
        if st.button("🗑  Meeting löschen"):
            st.session_state.confirm_delete = date_str
            st.rerun()


def page_new_project():
    st.title("🆕 Neues Projekt")
    with st.form("new_project_form"):
        name = st.text_input("Projektname", placeholder="z.B. Leitungsmeeting Kunde XY")
        if st.form_submit_button("Anlegen") and name.strip():
            safe = name.strip().replace(" ", "_").replace("/", "-")
            if safe in list_projects():
                st.error("Name bereits vergeben.")
            else:
                cfg = dict(DEFAULT_CONFIG)
                cfg["display_name"] = name.strip()
                save_project(safe, cfg)
                st.session_state.project = safe
                st.session_state.page = "config"
                st.rerun()


def page_config():
    st.title("⚙️ Einstellungen")
    config = get_config()
    if not config:
        st.warning("Kein Projekt geladen.")
        return

    tab1, tab2, tab3, tab4 = st.tabs([
        "Teilnehmer", "Verhaltensmetriken", "Notizfelder", "Meeting-Kennzahlen"
    ])

    with tab1:
        st.caption("Je Zeile ein aktiver Teilnehmer")

        def _save_participants():
            cfg = get_config()
            cfg["participants"] = [p.strip() for p in st.session_state.participants_text.splitlines() if p.strip()]
            save_project(st.session_state.project, cfg)
            st.toast("Gespeichert ✓")

        st.text_area("Teilnehmer", value="\n".join(config.get("participants", [])),
                     height=180, key="participants_text", on_change=_save_participants,
                     label_visibility="collapsed")

        inactive = config.get("inactive_participants", {})
        if inactive:
            st.markdown("**Inaktive Teilnehmer:**")
            for name, until in list(inactive.items()):
                c1, c2, c3 = st.columns([2, 2, 1])
                c1.markdown(f"~~{name}~~")
                c2.caption(f"inaktiv seit {datetime.strptime(until, '%Y-%m-%d').strftime('%d.%m.%Y')}")
                if c3.button("↩ Reaktivieren", key=f"reakt_{name}"):
                    cfg = get_config()
                    cfg.get("inactive_participants", {}).pop(name, None)
                    if name not in cfg.get("participants", []):
                        cfg["participants"].append(name)
                    save_project(st.session_state.project, cfg)
                    st.toast(f"{name} reaktiviert ✓")
                    st.rerun()

        st.divider()
        st.markdown("**Teilnehmer inaktivieren:**")
        active_pp = [p for p in config.get("participants", []) if p not in inactive]
        if active_pp:
            c1, c2, c3 = st.columns([2, 2, 1])
            sel_name = c1.selectbox("Person", active_pp, label_visibility="collapsed")
            until_date = c2.date_input("Aktiv bis", value=date.today(), label_visibility="collapsed")
            if c3.button("Inaktivieren"):
                cfg = get_config()
                cfg.setdefault("inactive_participants", {})[sel_name] = str(until_date)
                save_project(st.session_state.project, cfg)
                st.toast(f"{sel_name} inaktiviert ✓")
                st.rerun()

    def _render_list(tab_key, config_key, hint):
        cfg = get_config()
        items = cfg.get(config_key, [])
        st.caption(hint)
        for i, item in enumerate(items):
            c1, c2, c3 = st.columns([3, 3, 1])
            new_label = c1.text_input("Bezeichnung", value=item["label"],
                                      key=f"{tab_key}_l_{i}", label_visibility="collapsed")
            new_key = c2.text_input("Schlüssel", value=item["key"],
                                    key=f"{tab_key}_k_{i}", label_visibility="collapsed")
            if c3.button("🗑", key=f"{tab_key}_d_{i}"):
                items.pop(i)
                cfg[config_key] = items
                save_project(st.session_state.project, cfg)
                st.toast("Gelöscht ✓")
                st.rerun()
            items[i] = {"key": new_key.strip().replace(" ", "_"), "label": new_label.strip()}
        if st.button("➕ Hinzufügen", key=f"{tab_key}_add"):
            items.append({"key": f"metrik_{len(items)+1}", "label": "Neue Metrik"})
            cfg[config_key] = items
            save_project(st.session_state.project, cfg)
            st.rerun()
        if st.button("Speichern", key=f"{tab_key}_save"):
            cfg[config_key] = items
            save_project(st.session_state.project, cfg)
            st.toast("Gespeichert ✓")

    with tab2:
        _render_list("bm", "behavior_metrics", "Werden live pro Person gezählt")
    with tab3:
        _render_list("nc", "note_categories", "Freitext-Kategorien für Beobachtungen")
    with tab4:
        _render_list("mm", "meeting_metrics", "Meeting-weite Kennzahlen")


def page_capture():
    config = get_config()
    if not config:
        st.warning("Bitte zuerst ein Projekt konfigurieren.")
        return
    if not config.get("participants"):
        st.warning("Keine Teilnehmer konfiguriert.")
        if st.button("→ Konfiguration"):
            st.session_state.page = "config"
            st.rerun()
        return

    st.title("⚡ Meeting erfassen")

    c_date, c_dur = st.columns([2, 2])
    with c_date:
        session_date = st.date_input("Datum", value=date.today())
    date_str = str(session_date)

    # Reset grid if date changed
    if st.session_state.get("grid_date") != date_str:
        st.session_state.pop("meeting_started", None)

    _init_grid(config, date_str)

    with c_dur:
        st.number_input("Meetingdauer (Min)", min_value=0, step=5,
                        value=st.session_state.get("grid_dauer", 60),
                        key="dauer_input", on_change=_update_dauer)

    pp_options = ["—"] + config.get("participants", [])

    def _owner_idx():
        v = st.session_state.get("grid_owner", "")
        return pp_options.index(v) if v in pp_options else 0

    def _proto_idx():
        v = st.session_state.get("grid_protokollant", "")
        return pp_options.index(v) if v in pp_options else 0

    def _update_owner():
        v = st.session_state["sel_owner"]
        st.session_state.grid_owner = "" if v == "—" else v
        _autosave()

    def _update_proto():
        v = st.session_state["sel_proto"]
        st.session_state.grid_protokollant = "" if v == "—" else v
        _autosave()

    c_own, c_pro = st.columns(2)
    c_own.selectbox("🎙️ Moderator / Meeting Owner", pp_options,
                    index=_owner_idx(), key="sel_owner", on_change=_update_owner)
    c_pro.selectbox("📋 Protokollant", pp_options,
                    index=_proto_idx(), key="sel_proto", on_change=_update_proto)

    bm = config.get("behavior_metrics", [])
    active_pp = [p for p in config.get("participants", []) if is_active(config, p, date_str)]

    if not st.session_state.get("meeting_started"):
        st.divider()
        st.info("Datum und Dauer prüfen, dann Meeting starten.")
        if st.button("⚡ Meeting starten", type="primary", use_container_width=True):
            st.session_state.meeting_started = True
            st.session_state.grid_dauer = st.session_state.get("dauer_input",
                                           st.session_state.get("grid_dauer", 60))
            _autosave()
            st.rerun()
        return

    st.divider()

    # Grid header
    col_w = [2.2, 0.7, 0.8] + [1.8] * len(bm)
    hcols = st.columns(col_w)
    for col, label in zip(hcols, ["Teilnehmer", "Anw.", "Verz."] + [m["label"] for m in bm]):
        col.markdown(f'<div class="grid-header">{label}</div>', unsafe_allow_html=True)

    # Participant rows
    for p in active_pp:
        if p not in st.session_state.grid_counters:
            st.session_state.grid_counters[p] = {m["key"]: 0 for m in bm}

        rcols = st.columns(col_w)

        with rcols[0]:
            st.markdown(f'<div class="grid-name">{p}</div>', unsafe_allow_html=True)
        with rcols[1]:
            st.checkbox(p, value=st.session_state.grid_anwesend.get(p, False),
                        key=f"anw_{p}", label_visibility="collapsed",
                        on_change=_toggle_anw, args=(p,))
        with rcols[2]:
            st.number_input("v", value=st.session_state.grid_verzug.get(p, 0),
                            min_value=0, step=1, key=f"vz_{p}",
                            label_visibility="collapsed",
                            on_change=_update_verzug, args=(p,))

        for i, m in enumerate(bm):
            with rcols[3 + i]:
                val = st.session_state.grid_counters[p].get(m["key"], 0)
                bc1, bc2, bc3 = st.columns([1, 1, 1])
                bc1.button("−", key=f"d_{p}_{m['key']}", on_click=_make_dec(p, m["key"]),
                           use_container_width=True)
                bc2.markdown(f'<div class="counter-val">{val}</div>', unsafe_allow_html=True)
                bc3.button("+", key=f"i_{p}_{m['key']}", on_click=_make_inc(p, m["key"]),
                           use_container_width=True)

    st.divider()

    with st.expander("📝 Beobachtungen & Notizen", expanded=False):
        for n in config.get("note_categories", []):
            if n["key"] not in st.session_state.grid_notes:
                st.session_state.grid_notes[n["key"]] = ""
            st.session_state.grid_notes[n["key"]] = st.text_area(
                n["label"],
                value=st.session_state.grid_notes.get(n["key"], ""),
                key=f"note_{n['key']}", height=80,
            )

    st.divider()

    if st.button("✅  Meeting abschließen", type="primary", use_container_width=True):
        # Save notes (auto-save handles counters, but notes are only saved here)
        _autosave()
        st.session_state.pop("meeting_started", None)
        st.session_state.pop("grid_date", None)
        st.session_state.detail_date = date_str
        st.session_state.page = "meeting_detail"
        st.toast(f"Meeting vom {session_date.strftime('%d.%m.%Y')} gespeichert ✓")
        st.rerun()


def page_stats():
    st.title("📈 Auswertung")
    config = get_config()
    sessions = load_sessions(st.session_state.project)

    if len(sessions) < 2:
        st.info("Mindestens 2 Meetings für Auswertungen nötig.")
        return

    bm = config.get("behavior_metrics", [])
    all_participants = config.get("participants", [])
    inactive = config.get("inactive_participants", {})

    # For each session, build effective participant list (active at that date)
    dates = [datetime.strptime(s["date"], "%Y-%m-%d").strftime("%d.%m.%y") for s in sessions]

    def active_for(s):
        return [p for p in all_participants if is_active(config, p, s["date"])]

    tab1, tab2, tab3, tab4 = st.tabs([
        "Verhaltenskurven", "Meeting-Kennzahlen", "Teilnehmer-Vergleich", "Gesamtansicht"
    ])

    with tab1:
        st.subheader("Verlauf pro Person")
        if not bm:
            st.info("Keine Verhaltensmetriken konfiguriert.")
        else:
            sel_key = st.selectbox("Metrik", [m["key"] for m in bm],
                                   format_func=lambda k: next((m["label"] for m in bm if m["key"] == k), k))
            lbl = next((m["label"] for m in bm if m["key"] == sel_key), sel_key)

            # Participants with at least one active session
            shown = [p for p in all_participants
                     if any(is_active(config, p, s["date"]) for s in sessions)]
            n = len(shown)
            cols_n = min(4, n)
            rows_n = math.ceil(n / cols_n)

            subplot_titles = [f"{p} (inaktiv)" if p in inactive else p for p in shown]
            fig = make_subplots(
                rows=rows_n, cols=cols_n,
                subplot_titles=subplot_titles,
                shared_yaxes=True,
                horizontal_spacing=0.06,
                vertical_spacing=0.28,
            )
            # Global Y-max for shared scale
            all_vals = [
                s["participants"].get(p, {}).get("behavior", {}).get(sel_key, 0)
                for p in shown for s in sessions if is_active(config, p, s["date"])
            ]
            y_max = max(all_vals) if all_vals else 1

            for idx, p in enumerate(shown):
                r = idx // cols_n + 1
                c = idx % cols_n + 1
                x_v, y_v = [], []
                for s, d in zip(sessions, dates):
                    if is_active(config, p, s["date"]):
                        x_v.append(d)
                        y_v.append(s["participants"].get(p, {}).get("behavior", {}).get(sel_key, 0))
                color = "#7a9e9a" if p in inactive else "#59B2A5"
                dash = "dot" if p in inactive else "solid"
                fig.add_trace(
                    go.Scatter(
                        x=x_v, y=y_v, mode="lines+markers",
                        line=dict(color=color, width=2, dash=dash),
                        marker=dict(size=5, color=color),
                        fill="tozeroy", fillcolor="rgba(89,178,165,0.08)",
                        showlegend=False,
                        hovertemplate="%{x}: %{y}<extra></extra>",
                    ),
                    row=r, col=c,
                )
                fig.update_yaxes(range=[0, y_max * 1.15], row=r, col=c,
                                 gridcolor="#eaf3f1", tickfont=dict(size=9))
                fig.update_xaxes(row=r, col=c, tickangle=-45,
                                 tickfont=dict(size=8), gridcolor="#eaf3f1")

            fig.update_layout(
                height=rows_n * 260 + 40,
                paper_bgcolor="white", plot_bgcolor="white",
                font=dict(family="DM Sans", size=11),
                margin=dict(t=40, b=30, l=30, r=10),
            )
            for ann in fig.layout.annotations:
                ann.font = dict(size=12, color="#246b61", family="DM Sans")

            st.caption(f"**{lbl}** — jede Person in eigenem Chart, gleiche Y-Achse für direkte Vergleichbarkeit")
            st.plotly_chart(fig, use_container_width=True)

    with tab2:
        st.subheader("Meeting-Kennzahlen im Verlauf")
        rows = []
        for s in sessions:
            row = {"Datum": datetime.strptime(s["date"], "%Y-%m-%d").strftime("%d.%m.%y")}
            row.update(computed_metrics(s, config))
            for m in config.get("meeting_metrics", []):
                row[m["label"]] = s["meeting_metrics"].get(m["key"], 0)
            rows.append(row)
        df = pd.DataFrame(rows)
        num_cols = [c for c in df.columns if c != "Datum"]
        ndf = df.copy()
        for col in num_cols:
            ndf[col] = pd.to_numeric(
                ndf[col].astype(str).str.replace("%", "").str.replace("—", "0"), errors="coerce")
        avail = [c for c in num_cols if ndf[c].notna().any()]
        if avail:
            sel_kpi = st.multiselect("Kennzahlen", avail, default=avail[:2])
            if sel_kpi:
                fig2 = go.Figure()
                for i, col in enumerate(sel_kpi):
                    fig2.add_trace(go.Scatter(
                        x=df["Datum"], y=ndf[col], mode="lines+markers", name=col,
                        line=dict(color=TEAL[i % len(TEAL)], width=2),
                    ))
                fig2.update_layout(
                    height=380, paper_bgcolor="white", plot_bgcolor="white",
                    font=dict(family="DM Sans"),
                    xaxis=dict(gridcolor="#eaf3f1"), yaxis=dict(gridcolor="#eaf3f1"),
                )
                st.plotly_chart(fig2, use_container_width=True)
        st.dataframe(df.set_index("Datum"), use_container_width=True)

    with tab3:
        st.subheader("Vergleich Gesamtwerte")
        if not bm or not all_participants:
            st.info("Keine Daten.")
        else:
            summary = []
            for p in all_participants:
                row = {"Teilnehmer": p + (" ↩" if p in inactive else "")}
                row["Meetings"] = sum(
                    1 for s in sessions
                    if s["participants"].get(p, {}).get("anwesend") and is_active(config, p, s["date"])
                )
                for m in bm:
                    row[m["label"]] = sum(
                        s["participants"].get(p, {}).get("behavior", {}).get(m["key"], 0)
                        for s in sessions if is_active(config, p, s["date"])
                    )
                summary.append(row)
            df_s = pd.DataFrame(summary).set_index("Teilnehmer")
            st.dataframe(df_s, use_container_width=True)

            bar_key = st.selectbox("Balkendiagramm für",
                                   [m["key"] for m in bm],
                                   format_func=lambda k: next((m["label"] for m in bm if m["key"] == k), k),
                                   key="bar_key")
            bar_lbl = next((m["label"] for m in bm if m["key"] == bar_key), bar_key)
            bar_data = {
                p: sum(s["participants"].get(p, {}).get("behavior", {}).get(bar_key, 0)
                       for s in sessions if is_active(config, p, s["date"]))
                for p in all_participants
            }
            fig3 = px.bar(x=list(bar_data.keys()), y=list(bar_data.values()),
                          labels={"x": "Teilnehmer", "y": bar_lbl},
                          title=f"{bar_lbl} — Gesamtübersicht",
                          color_discrete_sequence=["#59B2A5"])
            fig3.update_layout(paper_bgcolor="white", plot_bgcolor="white",
                               font=dict(family="DM Sans"),
                               yaxis=dict(gridcolor="#eaf3f1"))
            st.plotly_chart(fig3, use_container_width=True)

    with tab4:
        st.subheader("Gesamtanzahl pro Meeting")
        if not bm:
            st.info("Keine Verhaltensmetriken konfiguriert.")
        else:
            sel = st.selectbox("Metrik", [m["key"] for m in bm],
                               format_func=lambda k: next((m["label"] for m in bm if m["key"] == k), k),
                               key="total_metric")
            sel_lbl = next((m["label"] for m in bm if m["key"] == sel), sel)
            totals = [
                sum(s["participants"].get(p, {}).get("behavior", {}).get(sel, 0)
                    for p in active_for(s))
                for s in sessions
            ]
            fig4 = px.bar(x=dates, y=totals,
                          labels={"x": "Meeting", "y": "Anzahl gesamt"},
                          title=f"{sel_lbl} — Gesamtanzahl pro Meeting",
                          color_discrete_sequence=["#59B2A5"])
            fig4.update_layout(xaxis_tickangle=-45, height=360,
                               paper_bgcolor="white", plot_bgcolor="white",
                               font=dict(family="DM Sans"),
                               yaxis=dict(gridcolor="#eaf3f1"))
            st.plotly_chart(fig4, use_container_width=True)

            st.subheader(f"{sel_lbl} — Verlauf pro Person")
            # Identitätsfarben: pro Person fest in project.json hinterlegt
            colors = person_colors(st.session_state.project, config)
            fig5 = go.Figure()
            active_shown = [p for p in all_participants
                            if any(is_active(config, p, s["date"]) for s in sessions)]
            for i, p in enumerate(active_shown):
                x_v, y_v = [], []
                for s, d in zip(sessions, dates):
                    if is_active(config, p, s["date"]):
                        x_v.append(d)
                        y_v.append(s["participants"].get(p, {}).get("behavior", {}).get(sel, 0))
                if y_v:
                    color = colors.get(p, "#2196A6")
                    fig5.add_trace(go.Scatter(
                        x=x_v, y=y_v, mode="lines+markers",
                        name=p + (" (inaktiv)" if p in inactive else ""),
                        line=dict(color=color, width=2.5,
                                  dash="dot" if p in inactive else "solid"),
                        marker=dict(size=7, color=color),
                        opacity=0.85,
                        hovertemplate=f"<b>{p}</b><br>%{{x}}: %{{y}}<extra></extra>",
                    ))
            fig5.update_layout(
                xaxis_title="Meeting", yaxis_title="Anzahl", height=400,
                paper_bgcolor="white", plot_bgcolor="white",
                font=dict(family="DM Sans"),
                xaxis=dict(gridcolor="#eaf3f1"),
                yaxis=dict(gridcolor="#eaf3f1"),
                hovermode="x unified",
                legend=dict(
                    orientation="v", bgcolor="rgba(255,255,255,0.9)",
                    bordercolor="#d4e8e5", borderwidth=1,
                    font=dict(size=12),
                ),
            )
            st.caption("Tipp: Doppelklick auf einen Namen in der Legende → Person isolieren")
            st.plotly_chart(fig5, use_container_width=True)

            tbl = pd.DataFrame(
                {p: [s["participants"].get(p, {}).get("behavior", {}).get(sel, 0)
                     if is_active(config, p, s["date"]) else None
                     for s in sessions]
                 for p in all_participants},
                index=dates,
            )
            tbl.index.name = "Meeting"
            tbl["Gesamt"] = tbl.sum(axis=1, numeric_only=True)
            st.dataframe(tbl, use_container_width=True)


# ── Router ─────────────────────────────────────────────────────────────────────

page = st.session_state.page
if page == "home":        page_home()
elif page == "new_project": page_new_project()
elif page == "config":    page_config()
elif page == "capture":   page_capture()
elif page == "insights":  page_insights()
elif page == "meeting_detail": page_meeting_detail()
elif page == "stats":     page_stats()
else:                     page_home()
