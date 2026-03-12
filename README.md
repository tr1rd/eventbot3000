# EventBot3000

Ein Discord-Bot für FiveM/RP-Familien zur Verwaltung von Events, Auszahlungen, Rängen und Blacklists.

> **Dokumentation:** [pawjobs.net/eventbot3000/docs](https://pawjobs.net/eventbot3000/docs)

---

## Features

- **Events** — Erstellen, Schließen, Abschließen mit automatischer Auszahlung
- **Wiederkehrende Events** — Stündlich, täglich oder wöchentlich planbar
- **Rang-System** — 11 Stufen (0–10) mit Discord-Rollen-Integration
- **Auszahlungen** — Anfahrt, Win/Loss, Kills, Assists; Live-Ranking im Channel
- **Blacklists** — Fam-Blacklist (Ingame-ID) und Event-Blacklist (Discord-ID)
- **Registrierung** — User anlegen mit Ingame-Name und ID

---

## Rang-System

| Rang | Name | Berechtigung |
|------|------|-------------|
| 0 | Nicht registriert |
| 1–6 | Basis-Commands |
| 7 |  `/register` |
| 8 | Events erstellen/verwalten |
| 9 | Blacklists, Payouts, Planung |
| 10 | Voller Zugriff |

---

## Tech Stack

- Python 3.10+
- [discord.py](https://github.com/Rapptz/discord.py) 2.3+
- SQLite
- python-dotenv

---

## Lizenz

MIT License - frei verwendbar und anpassbar.

