import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from app.storage import (
    list_projects, load_project, save_project,
    load_sessions, save_session, delete_session,
    new_session_template, DEFAULT_CONFIG,
)

st.set_page_config(page_title="Meeting Tracking", page_icon="📊", layout="wide")

# ── Session State ──────────────────────────────────────────────────────────────

if "project" not in st.session_state:
    st.session_state.project = None
if "page" not in st.session_state:
    st.session_state.page = "home"


def switch_page(page: str):
    st.session_state.page = page
    st.rerun()


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("📊 Meeting Tracking")
    projects = list_projects()

    if projects:
        selected = st.selectbox(
            "Projekt",
            options=["— Projekt wählen —"] + projects,
            index=0 if st.session_state.project is None else
                  (projects.index(st.session_state.project) + 1 if st.session_state.project in projects else 0),
        )
        if selected != "— Projekt wählen —":
            if st.session_state.project != selected:
                st.session_state.project = selected
                st.rerun()
    else:
        st.info("Noch kein Projekt. Lege eines an.")

    st.divider()

    if st.session_state.project:
        if st.button("🏠 Übersicht", use_container_width=True):
            switch_page("overview")
        if st.button("➕ Meeting erfassen", use_container_width=True):
            switch_page("capture")
        if st.button("📈 Auswertung", use_container_width=True):
            switch_page("stats")
        if st.button("⚙️ Projekt konfigurieren", use_container_width=True):
            switch_page("config")
        st.divider()

    if st.button("🆕 Neues Projekt", use_container_width=True):
        switch_page("new_project")


# ── Helper ─────────────────────────────────────────────────────────────────────

def get_config() -> dict:
    if not st.session_state.project:
        return {}
    return load_project(st.session_state.project)


def computed_metrics(session: dict, config: dict) -> dict:
    dauer = session["meeting_metrics"].get("dauer_min", 0)
    participants = session["participants"]

    total_interruptions = sum(
        p["behavior"].get("unterbrechung", 0) for p in participants.values()
    )
    total_present_min = sum(p.get("anwesend_min", 0) for p in participants.values())
    required_count = sum(1 for p in participants.values() if p.get("notwendig"))
    max_possible = required_count * dauer if required_count and dauer else 0
    attendance_ratio = total_present_min / max_possible if max_possible > 0 else None
    interruption_interval = dauer / total_interruptions if (dauer and total_interruptions) else None
    blocked_ratio = total_interruptions / dauer if dauer else None

    return {
        "Unterbrechungen gesamt": total_interruptions,
        "Unterbrechung alle (Min)": round(interruption_interval, 1) if interruption_interval else "—",
        "Freie Rede blockiert": f"{blocked_ratio:.1%}" if blocked_ratio is not None else "—",
        "Anwesenheit/Deckung": f"{attendance_ratio:.1%}" if attendance_ratio is not None else "—",
        "Geringschätzung gesamt": sum(p["behavior"].get("geringschaetzend", 0) for p in participants.values()),
        "Hand gehoben gesamt": sum(p["behavior"].get("hand_gehoben", 0) for p in participants.values()),
    }


# ── Pages ──────────────────────────────────────────────────────────────────────

def page_home():
    st.title("Meeting Tracking")
    st.markdown("Wähle links ein Projekt oder lege ein neues an.")


def page_new_project():
    st.title("🆕 Neues Projekt anlegen")

    with st.form("new_project_form"):
        name = st.text_input("Projektname", placeholder="z.B. Leitungsmeeting Kunde XY")
        submitted = st.form_submit_button("Projekt anlegen")

    if submitted and name.strip():
        safe_name = name.strip().replace(" ", "_").replace("/", "-")
        if safe_name in list_projects():
            st.error("Ein Projekt mit diesem Namen existiert bereits.")
        else:
            config = dict(DEFAULT_CONFIG)
            config["display_name"] = name.strip()
            save_project(safe_name, config)
            st.session_state.project = safe_name
            st.success(f"Projekt '{name}' angelegt.")
            switch_page("config")


def page_config():
    st.title("⚙️ Projekt konfigurieren")
    config = get_config()
    if not config:
        st.warning("Kein Projekt geladen.")
        return

    tab1, tab2, tab3, tab4 = st.tabs(["Teilnehmer", "Verhaltensmetriken", "Notizfelder", "Meeting-Kennzahlen"])

    with tab1:
        st.subheader("Teilnehmer")
        participants = config.get("participants", [])
        updated = st.text_area(
            "Je Zeile ein Name",
            value="\n".join(participants),
            height=200,
        )
        if st.button("Speichern", key="save_participants"):
            config["participants"] = [p.strip() for p in updated.splitlines() if p.strip()]
            save_project(st.session_state.project, config)
            st.success("Gespeichert.")
            st.rerun()

    with tab2:
        st.subheader("Verhaltensmetriken (pro Person)")
        metrics = config.get("behavior_metrics", [])
        st.markdown("Diese Felder werden pro Person pro Meeting gezählt (Ganzzahl).")

        for i, m in enumerate(metrics):
            c1, c2, c3 = st.columns([3, 3, 1])
            with c1:
                new_label = st.text_input("Bezeichnung", value=m["label"], key=f"bm_label_{i}")
            with c2:
                new_key = st.text_input("Schlüssel (kein Leerzeichen)", value=m["key"], key=f"bm_key_{i}")
            with c3:
                st.write("")
                if st.button("🗑", key=f"bm_del_{i}"):
                    metrics.pop(i)
                    config["behavior_metrics"] = metrics
                    save_project(st.session_state.project, config)
                    st.rerun()
            metrics[i] = {"key": new_key.strip().replace(" ", "_"), "label": new_label.strip()}

        if st.button("➕ Metrik hinzufügen", key="add_bm"):
            metrics.append({"key": f"metrik_{len(metrics)+1}", "label": "Neue Metrik"})
            config["behavior_metrics"] = metrics
            save_project(st.session_state.project, config)
            st.rerun()

        if st.button("Speichern", key="save_bm"):
            config["behavior_metrics"] = metrics
            save_project(st.session_state.project, config)
            st.success("Gespeichert.")

    with tab3:
        st.subheader("Qualitative Notizfelder")
        note_cats = config.get("note_categories", [])

        for i, n in enumerate(note_cats):
            c1, c2, c3 = st.columns([3, 3, 1])
            with c1:
                new_label = st.text_input("Bezeichnung", value=n["label"], key=f"nc_label_{i}")
            with c2:
                new_key = st.text_input("Schlüssel", value=n["key"], key=f"nc_key_{i}")
            with c3:
                st.write("")
                if st.button("🗑", key=f"nc_del_{i}"):
                    note_cats.pop(i)
                    config["note_categories"] = note_cats
                    save_project(st.session_state.project, config)
                    st.rerun()
            note_cats[i] = {"key": new_key.strip().replace(" ", "_"), "label": new_label.strip()}

        if st.button("➕ Notizfeld hinzufügen", key="add_nc"):
            note_cats.append({"key": f"notiz_{len(note_cats)+1}", "label": "Neues Notizfeld"})
            config["note_categories"] = note_cats
            save_project(st.session_state.project, config)
            st.rerun()

        if st.button("Speichern", key="save_nc"):
            config["note_categories"] = note_cats
            save_project(st.session_state.project, config)
            st.success("Gespeichert.")

    with tab4:
        st.subheader("Meeting-Kennzahlen (Meeting-weit)")
        mm = config.get("meeting_metrics", [])

        for i, m in enumerate(mm):
            c1, c2, c3 = st.columns([3, 3, 1])
            with c1:
                new_label = st.text_input("Bezeichnung", value=m["label"], key=f"mm_label_{i}")
            with c2:
                new_key = st.text_input("Schlüssel", value=m["key"], key=f"mm_key_{i}")
            with c3:
                st.write("")
                if st.button("🗑", key=f"mm_del_{i}"):
                    mm.pop(i)
                    config["meeting_metrics"] = mm
                    save_project(st.session_state.project, config)
                    st.rerun()
            mm[i] = {"key": new_key.strip().replace(" ", "_"), "label": new_label.strip()}

        if st.button("➕ Kennzahl hinzufügen", key="add_mm"):
            mm.append({"key": f"kennzahl_{len(mm)+1}", "label": "Neue Kennzahl"})
            config["meeting_metrics"] = mm
            save_project(st.session_state.project, config)
            st.rerun()

        if st.button("Speichern", key="save_mm"):
            config["meeting_metrics"] = mm
            save_project(st.session_state.project, config)
            st.success("Gespeichert.")


def page_capture():
    st.title("➕ Meeting erfassen")
    config = get_config()
    if not config:
        st.warning("Bitte zuerst ein Projekt konfigurieren.")
        return
    if not config.get("participants"):
        st.warning("Keine Teilnehmer konfiguriert. Bitte zuerst Teilnehmer anlegen.")
        if st.button("→ Konfiguration öffnen"):
            switch_page("config")
        return

    sessions = load_sessions(st.session_state.project)
    existing_dates = [s["date"] for s in sessions]

    st.subheader("Datum")
    session_date = st.date_input("Meeting-Datum", value=date.today())
    date_str = str(session_date)

    if date_str in existing_dates:
        st.info("Für dieses Datum existiert bereits ein Eintrag. Beim Speichern wird er überschrieben.")
        existing = next(s for s in sessions if s["date"] == date_str)
        session = existing
    else:
        session = new_session_template(config, date_str)

    # Meeting-Kennzahlen
    st.subheader("Meeting-Kennzahlen")
    mm_cols = st.columns(min(len(config.get("meeting_metrics", [])), 4))
    for i, m in enumerate(config.get("meeting_metrics", [])):
        with mm_cols[i % len(mm_cols)]:
            session["meeting_metrics"][m["key"]] = st.number_input(
                m["label"],
                min_value=0,
                value=int(session["meeting_metrics"].get(m["key"], 0)),
                key=f"mm_{m['key']}",
            )

    # Teilnehmer
    st.subheader("Teilnehmer")
    behavior_metrics = config.get("behavior_metrics", [])

    for participant in config.get("participants", []):
        if participant not in session["participants"]:
            session["participants"][participant] = {
                "notwendig": False, "optional": False, "anwesend": False,
                "verzug_min": 0, "frueher_raus_min": 0, "anwesend_min": 0,
                "behavior": {m["key"]: 0 for m in behavior_metrics},
            }
        p = session["participants"][participant]

        with st.expander(f"**{participant}**", expanded=True):
            c1, c2, c3, c4, c5, c6 = st.columns([1, 1, 1, 1, 1, 1])
            with c1:
                p["notwendig"] = st.checkbox("Notwendig", value=p.get("notwendig", False), key=f"{participant}_notwendig")
            with c2:
                p["optional"] = st.checkbox("Optional", value=p.get("optional", False), key=f"{participant}_optional")
            with c3:
                p["anwesend"] = st.checkbox("Anwesend", value=p.get("anwesend", False), key=f"{participant}_anwesend")
            with c4:
                p["verzug_min"] = st.number_input("Verzug (Min)", min_value=0, value=int(p.get("verzug_min", 0)), key=f"{participant}_verzug")
            with c5:
                p["frueher_raus_min"] = st.number_input("Früher raus (Min)", min_value=0, value=int(p.get("frueher_raus_min", 0)), key=f"{participant}_raus")
            with c6:
                p["anwesend_min"] = st.number_input("Anwesend (Min)", min_value=0, value=int(p.get("anwesend_min", 0)), key=f"{participant}_min")

            if behavior_metrics:
                bm_cols = st.columns(len(behavior_metrics))
                for j, m in enumerate(behavior_metrics):
                    with bm_cols[j]:
                        if "behavior" not in p:
                            p["behavior"] = {}
                        p["behavior"][m["key"]] = st.number_input(
                            m["label"],
                            min_value=0,
                            value=int(p["behavior"].get(m["key"], 0)),
                            key=f"{participant}_{m['key']}",
                        )

        session["participants"][participant] = p

    # Notizen
    st.subheader("Beobachtungen & Notizen")
    for n in config.get("note_categories", []):
        if n["key"] not in session["notes"]:
            session["notes"][n["key"]] = ""
        session["notes"][n["key"]] = st.text_area(
            n["label"],
            value=session["notes"].get(n["key"], ""),
            key=f"note_{n['key']}",
            height=100,
        )

    st.divider()
    if st.button("💾 Speichern", type="primary", use_container_width=True):
        save_session(st.session_state.project, session)
        st.success(f"Meeting vom {session_date.strftime('%d.%m.%Y')} gespeichert.")
        st.balloons()


def page_overview():
    st.title("🏠 Übersicht")
    config = get_config()
    sessions = load_sessions(st.session_state.project)

    project_name = config.get("display_name", st.session_state.project)
    st.subheader(project_name)

    if not sessions:
        st.info("Noch keine Meetings erfasst.")
        if st.button("➕ Erstes Meeting erfassen"):
            switch_page("capture")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Meetings erfasst", len(sessions))
    with col2:
        st.metric("Teilnehmer", len(config.get("participants", [])))
    with col3:
        last = sessions[-1]["date"]
        st.metric("Letztes Meeting", datetime.strptime(last, "%Y-%m-%d").strftime("%d.%m.%Y"))

    st.divider()
    st.subheader("Alle Meetings")

    for s in reversed(sessions):
        date_label = datetime.strptime(s["date"], "%Y-%m-%d").strftime("%d.%m.%Y")
        dauer = s["meeting_metrics"].get("dauer_min", "?")
        present = sum(1 for p in s["participants"].values() if p.get("anwesend"))
        total = len(s["participants"])
        cm = computed_metrics(s, config)

        with st.expander(f"**{date_label}** — {present}/{total} anwesend, {dauer} Min"):
            m_cols = st.columns(3)
            items = list(cm.items())
            for i, (k, v) in enumerate(items):
                with m_cols[i % 3]:
                    st.metric(k, v)

            if any(v for v in s["notes"].values()):
                st.markdown("**Notizen:**")
                for n in config.get("note_categories", []):
                    txt = s["notes"].get(n["key"], "")
                    if txt:
                        st.markdown(f"*{n['label']}:* {txt}")

            if st.button("🗑 Löschen", key=f"del_{s['date']}"):
                delete_session(st.session_state.project, s["date"])
                st.rerun()


def page_stats():
    st.title("📈 Auswertung")
    config = get_config()
    sessions = load_sessions(st.session_state.project)

    if len(sessions) < 2:
        st.info("Mindestens 2 Meetings erforderlich für Auswertungen.")
        return

    behavior_metrics = config.get("behavior_metrics", [])
    participants = config.get("participants", [])
    dates = [datetime.strptime(s["date"], "%Y-%m-%d").strftime("%d.%m.%y") for s in sessions]

    tab1, tab2, tab3 = st.tabs(["Verhaltenskurven", "Meeting-Kennzahlen", "Teilnehmer-Vergleich"])

    with tab1:
        st.subheader("Verhaltenskurven pro Person")
        if not behavior_metrics:
            st.info("Keine Verhaltensmetriken konfiguriert.")
        else:
            selected_metric = st.selectbox(
                "Metrik",
                options=[m["key"] for m in behavior_metrics],
                format_func=lambda k: next((m["label"] for m in behavior_metrics if m["key"] == k), k),
            )
            fig = go.Figure()
            for p in participants:
                values = [
                    s["participants"].get(p, {}).get("behavior", {}).get(selected_metric, 0)
                    for s in sessions
                ]
                fig.add_trace(go.Scatter(x=dates, y=values, mode="lines+markers", name=p))
            metric_label = next((m["label"] for m in behavior_metrics if m["key"] == selected_metric), selected_metric)
            fig.update_layout(title=metric_label, xaxis_title="Meeting", yaxis_title="Anzahl", height=400)
            st.plotly_chart(fig, use_container_width=True)

    with tab2:
        st.subheader("Meeting-Kennzahlen im Verlauf")

        computed_rows = []
        for s in sessions:
            row = {"Datum": datetime.strptime(s["date"], "%Y-%m-%d").strftime("%d.%m.%y")}
            row.update(computed_metrics(s, config))
            for m in config.get("meeting_metrics", []):
                row[m["label"]] = s["meeting_metrics"].get(m["key"], 0)
            computed_rows.append(row)

        df = pd.DataFrame(computed_rows)

        numeric_cols = [c for c in df.columns if c != "Datum"]
        numeric_df = df.copy()
        for col in numeric_cols:
            try:
                numeric_df[col] = pd.to_numeric(
                    numeric_df[col].astype(str).str.replace("%", "").str.replace("—", "0"),
                    errors="coerce"
                )
            except Exception:
                pass

        available = [c for c in numeric_cols if numeric_df[c].notna().any()]
        if available:
            selected_kpi = st.multiselect("Kennzahlen auswählen", options=available, default=available[:2])
            if selected_kpi:
                fig2 = go.Figure()
                for col in selected_kpi:
                    fig2.add_trace(go.Scatter(x=df["Datum"], y=numeric_df[col], mode="lines+markers", name=col))
                fig2.update_layout(xaxis_title="Meeting", height=400)
                st.plotly_chart(fig2, use_container_width=True)

        st.dataframe(df.set_index("Datum"), use_container_width=True)

    with tab3:
        st.subheader("Teilnehmer-Vergleich (Gesamt)")
        if not behavior_metrics or not participants:
            st.info("Keine Daten vorhanden.")
        else:
            summary = []
            for p in participants:
                row = {"Teilnehmer": p}
                meetings_attended = sum(1 for s in sessions if s["participants"].get(p, {}).get("anwesend", False))
                row["Meetings anwesend"] = meetings_attended
                for m in behavior_metrics:
                    total = sum(
                        s["participants"].get(p, {}).get("behavior", {}).get(m["key"], 0)
                        for s in sessions
                    )
                    row[m["label"]] = total
                summary.append(row)

            df_sum = pd.DataFrame(summary).set_index("Teilnehmer")
            st.dataframe(df_sum, use_container_width=True)

            if behavior_metrics:
                bar_metric = st.selectbox(
                    "Balkendiagramm für",
                    options=[m["key"] for m in behavior_metrics],
                    format_func=lambda k: next((m["label"] for m in behavior_metrics if m["key"] == k), k),
                    key="bar_metric",
                )
                bar_label = next((m["label"] for m in behavior_metrics if m["key"] == bar_metric), bar_metric)
                bar_data = {
                    p: sum(s["participants"].get(p, {}).get("behavior", {}).get(bar_metric, 0) for s in sessions)
                    for p in participants
                }
                fig3 = px.bar(
                    x=list(bar_data.keys()),
                    y=list(bar_data.values()),
                    labels={"x": "Teilnehmer", "y": bar_label},
                    title=f"{bar_label} — Gesamtübersicht",
                )
                st.plotly_chart(fig3, use_container_width=True)


# ── Router ─────────────────────────────────────────────────────────────────────

page = st.session_state.page

if page == "home":
    page_home()
elif page == "new_project":
    page_new_project()
elif page == "config":
    page_config()
elif page == "capture":
    page_capture()
elif page == "overview":
    page_overview()
elif page == "stats":
    page_stats()
else:
    page_home()
