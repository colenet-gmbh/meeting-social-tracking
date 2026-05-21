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
└── MeinProjekt/
    ├── project.json   # Konfiguration (Teilnehmer, Metriken, Felder)
    └── sessions.json  # Alle erfassten Meetings
```

**Neues Projekt für neuen Kunden:** Einfach in der App „Neues Projekt" anlegen — der `data/`-Ordner bleibt lokal und geht nie ins Repo.

## Funktionen

- **Mehrere Projekte** mit je eigenen Teilnehmern und Metriken
- **Flexible Konfiguration:** Teilnehmer, Verhaltensmetriken, Notizfelder und Meeting-Kennzahlen frei anpassbar
- **Datenerfassung** pro Meeting: Anwesenheit, Pünktlichkeit, Verhalten pro Person, qualitative Notizen
- **Auswertung:** Zeitreihen-Kurven, Meeting-Kennzahlen, Teilnehmer-Vergleich
- **Berechnete Metriken:** Unterbrechungsquotient, Anwesenheit/Deckung, Freie Rede blockiert
