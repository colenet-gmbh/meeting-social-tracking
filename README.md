# Meeting Social Tracking

Agiles Meeting-Beobachtungs-Tool für Führungskräfteentwicklung und Coaching.

## Starten

```bash
pip install -r requirements.txt
streamlit run app.py
```

Die App öffnet sich automatisch im Browser unter `http://localhost:8501`.

## Daten

Alle Daten liegen im Ordner `data/` — dieser ist **nicht** im Repository enthalten (`.gitignore`).

Für jedes Projekt gibt es einen eigenen Unterordner:
```
data/
├── app_state.json     # Zuletzt genutztes Projekt (Auto-Einstieg)
└── MeinProjekt/
    ├── project.json   # Konfiguration (Teilnehmer, Metriken, Felder, Personenfarben)
    └── sessions.json  # Alle erfassten Meetings
```

**Neues Projekt für neuen Kunden:** Einfach in der App „Neues Projekt" anlegen — der `data/`-Ordner bleibt lokal und geht nie ins Repo.

## Aufbau

- **Start:** Projekt-Home mit „Meeting starten", Kompaktstatus und klickbarer Meeting-Historie. Die App öffnet direkt das zuletzt genutzte Projekt.
- **Meeting erfassen:** Live-Grid mit Zählern pro Person und Autosave. Der Abschluss führt zur Meeting-Zusammenfassung.
- **Meeting-Zusammenfassung:** Kennzahlen mit Einordnung gegenüber den letzten Meetings, Verhalten pro Person, Notizen (werden sofort gespeichert), Löschen. Dieselbe Ansicht öffnet historische Meetings.
- **Insights:** Regelbasierte Auswertung — Team-Klima-Score (0–100), automatische Befunde (Trends, Ausreißer, Ungleichgewichte) mit Beleg-Chart, Teilnehmer-Karten mit Trendpfeilen. Logik in `app/analytics.py` (alle Schwellen als Konstanten am Dateianfang), Darstellung in `app/insights_ui.py`.
- **Auswertung:** Zeitreihen-Kurven, Meeting-Kennzahlen, Teilnehmer-Vergleich.
- **Einstellungen:** Teilnehmer (inkl. Inaktivierung), Verhaltensmetriken, Notizfelder, Meeting-Kennzahlen.

Alle Insight-Berechnungen nutzen Raten (Ereignisse pro Stunde Anwesenheit) statt Rohzahlen. Status wird immer als Icon + Wort + Begründung dargestellt; Ampelfarben sind strikt von den Personen-Identitätsfarben getrennt.

## Tests

```bash
python3 -m pytest tests/
```
