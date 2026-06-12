"""Insights-Seite: Team-Status, automatische Befunde mit Beleg, Teilnehmer-Karten.

Statusdarstellung immer Icon + Wort + Begründung; Ampelfarben nur als
Badge-Hintergrund, nie als Personen- oder Linienfarbe.
"""

from __future__ import annotations

import streamlit as st
import plotly.graph_objects as go
from datetime import datetime

from app.storage import load_sessions, load_project
from app.analytics import (
    TREND_WINDOW, climate_series, climate_status, generate_findings,
    participant_card, fmt_de, is_active,
)

MAX_FINDINGS_VISIBLE = 7
STATUS_BG = {"🟢": "#eaf6ec", "🟡": "#fdf6e3", "🔴": "#fdecea"}
STATUS_BORDER = {"🟢": "#bfe3c6", "🟡": "#f0e0a8", "🔴": "#f2c4bf"}


def _short_dates(dates: list[str]) -> list[str]:
    return [datetime.strptime(d, "%Y-%m-%d").strftime("%d.%m.%y") for d in dates]


def _spark(dates: list[str], values: list[float], label: str,
           split_idx: int | None = None, height: int = 200) -> go.Figure:
    """Teal-Sparkline; das jüngste Vergleichsfenster wird dezent hinterlegt."""
    x = _short_dates(dates)
    fig = go.Figure(go.Scatter(
        x=x, y=values, mode="lines+markers",
        line=dict(color="#3a8a7e", width=2),
        marker=dict(size=5, color="#3a8a7e"),
        fill="tozeroy", fillcolor="rgba(89,178,165,0.06)",
        hovertemplate="%{x}: %{y:.1f}<extra></extra>",
    ))
    if split_idx and 0 < split_idx < len(x):
        fig.add_vrect(x0=x[split_idx] if split_idx < len(x) else x[-1], x1=x[-1],
                      fillcolor="rgba(89,178,165,0.12)", line_width=0,
                      annotation_text="Vergleichsfenster", annotation_position="top left",
                      annotation_font=dict(size=10, color="#246b61"))
    fig.update_layout(
        title=dict(text=label, font=dict(size=12)),
        height=height, margin=dict(l=10, r=10, t=34, b=20),
        paper_bgcolor="white", plot_bgcolor="white",
        font=dict(family="DM Sans", size=11),
        xaxis=dict(showgrid=False, tickfont=dict(size=9), tickangle=-45),
        yaxis=dict(gridcolor="#eaf3f1", tickfont=dict(size=9), rangemode="tozero"),
    )
    return fig


def _zone_team_status(sessions: list, config: dict):
    series = climate_series(sessions, config)
    scores = [sc for _, sc in series]
    recent = scores[-TREND_WINDOW:]
    prior = scores[-2 * TREND_WINDOW:-TREND_WINDOW] or scores[:-TREND_WINDOW]
    avg_recent = sum(recent) / len(recent)
    avg_prior = sum(prior) / len(prior) if prior else None
    icon, word = climate_status(avg_recent)

    from app.analytics import climate_score
    _, reasons = climate_score(sessions[-1], config)
    vergleich = f", zuvor {avg_prior:.0f}" if avg_prior is not None else ""

    c1, c2 = st.columns([1.4, 1])
    with c1:
        st.markdown(
            f"""<div style="background:{STATUS_BG[icon]}; border:1px solid {STATUS_BORDER[icon]};
                 border-radius:12px; padding:16px 20px;">
                 <div style="font-size:1.25rem; font-weight:600; color:#1a2e2c;">
                   {icon} {word} — Klima-Score {avg_recent:.0f}/100</div>
                 <div style="color:#4a6b67; font-size:0.85rem; margin-top:2px;">
                   Ø der letzten {len(recent)} Meetings{vergleich}</div>
                 <div style="color:#1a2e2c; font-size:0.9rem; margin-top:8px;">
                   Letztes Meeting: {" · ".join(reasons)}</div>
               </div>""",
            unsafe_allow_html=True,
        )
        st.caption("Der Score gewichtet Unterbrechungs- und Geringschätzungsrate, "
                   "Konstruktiv-Rate, Anwesenheit und Verzug (0–100).")
    with c2:
        st.plotly_chart(
            _spark([d for d, _ in series], scores, "Klima-Score im Verlauf",
                   split_idx=max(len(series) - TREND_WINDOW, 0), height=190),
            use_container_width=True,
        )


def _zone_findings(sessions: list, config: dict):
    st.subheader("Befunde")
    findings = generate_findings(sessions, config)
    if not findings:
        st.info("Noch keine auffälligen Entwicklungen — dafür braucht es mindestens "
                f"{TREND_WINDOW + 2} Meetings mit Daten.")
        return

    def render(f, idx):
        if f.evidence:
            with st.expander(f"{f.icon} **{f.status_word}** — {f.text}"):
                st.plotly_chart(
                    _spark(f.evidence["dates"], f.evidence["values"],
                           f.evidence["label"], f.evidence.get("split_idx")),
                    use_container_width=True, key=f"finding_chart_{idx}",
                )
        else:
            st.markdown(f"{f.icon} **{f.status_word}** — {f.text}")

    for idx, f in enumerate(findings[:MAX_FINDINGS_VISIBLE]):
        render(f, idx)
    rest = findings[MAX_FINDINGS_VISIBLE:]
    if rest:
        with st.expander(f"… {len(rest)} weitere Befunde"):
            for idx, f in enumerate(rest, start=MAX_FINDINGS_VISIBLE):
                render(f, idx)


def _zone_participant_cards(sessions: list, config: dict):
    st.subheader("Teilnehmer")
    last_date = sessions[-1]["date"]
    persons = [p for p in config.get("participants", []) if is_active(config, p, last_date)]
    if not persons:
        return

    cols_n = 3
    for row_start in range(0, len(persons), cols_n):
        cols = st.columns(cols_n)
        for col, person in zip(cols, persons[row_start:row_start + cols_n]):
            card = participant_card(sessions, config, person)
            tags = " ".join(
                f'<span style="background:#e8f6f4; color:#246b61; border-radius:8px; '
                f'padding:1px 8px; font-size:0.72rem;">{t}</span>'
                for t in card["tags"]
            )
            lines = ""
            for m in card["metrics"]:
                rate = f"{fmt_de(m.rate)}/h" if m.rate is not None else "—"
                delta = (f" ({m.delta_pct:+.0%})"
                         if m.delta_pct is not None and m.word in ("verbessert", "verschlechtert")
                         else "")
                lines += (
                    f'<div style="display:flex; justify-content:space-between; '
                    f'font-size:0.83rem; padding:2px 0; border-bottom:1px solid #f2f7f6;">'
                    f'<span style="color:#4a6b67;">{m.label}</span>'
                    f'<span style="font-family:DM Mono,monospace; color:#1a2e2c;">'
                    f'{m.arrow} {rate} <span style="color:#4a6b67;">{m.word}{delta}</span>'
                    f'</span></div>'
                )
            att = f"{card['attendance']:.0%}" if card["attendance"] is not None else "—"
            with col:
                st.markdown(
                    f"""<div style="background:white; border:1px solid #d4e8e5; border-radius:12px;
                         padding:12px 16px; margin-bottom:14px; box-shadow:0 1px 3px rgba(89,178,165,0.08);">
                         <div style="display:flex; justify-content:space-between; align-items:center;">
                           <span style="font-weight:600; color:#1a2e2c;">{card["person"]}</span>
                           <span>{tags}</span>
                         </div>
                         <div style="margin-top:6px;">{lines}</div>
                         <div style="color:#4a6b67; font-size:0.76rem; margin-top:6px;">
                           Anwesenheit {att} · Ø Verzug {fmt_de(card["avg_verzug"], 0)} Min</div>
                       </div>""",
                    unsafe_allow_html=True,
                )
    st.caption(f"Raten = Ereignisse pro Stunde Anwesenheit, Ø der letzten {TREND_WINDOW} "
               f"besuchten Meetings; Pfeile vergleichen mit den {TREND_WINDOW} Meetings davor.")


def page_insights():
    st.title("💡 Insights")
    config = load_project(st.session_state.project) if st.session_state.project else {}
    if not config:
        st.warning("Kein Projekt geladen.")
        return
    sessions = load_sessions(st.session_state.project)
    if len(sessions) < 3:
        st.info("Für Insights braucht es mindestens 3 erfasste Meetings.")
        return

    _zone_team_status(sessions, config)
    st.divider()
    _zone_findings(sessions, config)
    st.divider()
    _zone_participant_cards(sessions, config)
