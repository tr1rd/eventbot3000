# EventBot3000

Ein Discord-Bot für FiveM/RP-Familien zur Verwaltung von Events, Auszahlungen, Rängen und Blacklists.

> **Dokumentation:** [eventbot3000.pawjobs.net](https://pawjobs.net/eventbot3000)

---

## Features

- **Events** — Erstellen, Schließen, Abschließen mit automatischer Auszahlung
- **Wiederkehrende Events** — Stündlich, täglich oder wöchentlich planbar
- **Rang-System** — 11 Stufen (0–10) mit Discord-Rollen-Integration
- **Auszahlungen** — Anfahrt, Win/Loss, Kills, Assists; Live-Ranking im Channel
- **Blacklists** — Fam-Blacklist (Ingame-ID) und Event-Blacklist (Discord-ID)
- **Registrierung** — User anlegen mit Ingame-Name und ID

---

## Setup

### 1. Bot auf Discord erstellen

1. [discord.com/developers/applications](https://discord.com/developers/applications) → **New Application**
2. **Bot** → Token kopieren
3. **Privileged Gateway Intents** → alle drei aktivieren
4. **OAuth2 → URL Generator** → Scopes: `bot`, `applications.commands`
5. Permissions: `Send Messages`, `Manage Roles`, `Read Message History`, `Embed Links`
6. Invite-Link öffnen und Bot zum Server hinzufügen

### 2. Projekt einrichten

```bash
git clone https://github.com/DEIN-NAME/eventbot3000.git
cd eventbot3000
pip install -r requirements.txt
```

### 3. `.env` Datei anlegen

```bash
cp .env.example .env
```

`.env` ausfüllen:

```env
BOT_TOKEN=dein_token_hier
GUILD_ID=deine_server_id

ADMIN_CHANNEL=channel_id
LOG_CHANNEL=channel_id
EVENT_CHANNEL=channel_id
PAYOUT_CHANNEL=channel_id
```

> **Channel-IDs:** Discord-Einstellungen → Erweitert → Entwicklermodus an, dann Rechtsklick auf Channel → ID kopieren

### 4. Bot starten

```bash
python bot.py
# oder
bash start.sh
```

### 5. Ersteinrichtung im Discord

```
/admin-rolle-setzen rolle:@DeineAdminRolle
/rang-setup
```

---

## Rang-System

| Rang | Name | Berechtigung |
|------|------|-------------|
| 0 | Gast | Nicht registriert |
| 1–6 | Mitglied | Basis-Commands |
| 7 | Hauptmann | `/register` |
| 8 | Offizier | Events erstellen/verwalten |
| 9 | Vize-Boss | Blacklists, Payouts, Planung |
| 10 | Boss | Voller Zugriff |

---

## Tech Stack

- Python 3.10+
- [discord.py](https://github.com/Rapptz/discord.py) 2.3+
- SQLite (keine externe DB nötig)
- python-dotenv

---

## Lizenz

MIT License — frei verwendbar und anpassbar.
