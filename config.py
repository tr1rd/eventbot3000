import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN  = os.getenv("BOT_TOKEN")
GUILD_ID   = int(os.getenv("GUILD_ID", "0"))

# Channel IDs
ADMIN_CHANNEL  = int(os.getenv("ADMIN_CHANNEL",  "0"))
LOG_CHANNEL    = int(os.getenv("LOG_CHANNEL",    "0"))
EVENT_CHANNEL  = int(os.getenv("EVENT_CHANNEL",  "0"))
PAYOUT_CHANNEL = int(os.getenv("PAYOUT_CHANNEL", "0"))

# Rang-System  (0 = Gast, 1-10 = Mitglied bis Boss)
RANKS = {
    0:  "Gast",
    1:  "Rekrut",
    2:  "Soldat",
    3:  "Enforcer",
    4:  "Veteran",
    5:  "Sergeant",
    6:  "Leutnant",
    7:  "Hauptmann",
    8:  "Offizier",
    9:  "Vize-Boss",
    10: "Boss",
}

# Ab diesem Rang darf man Events/Payouts/Blacklists verwalten
MANAGEMENT_MIN_RANK = 9

# Event-Typen
EVENT_TYPES = [
    "Famwar",
    "Bizwar",
    "Weinberge",
    "Waffenfabrik",
    "Statecontrol",
    "Bankraub",
    "Drogenrun",
    "Convoy",
    "Rivalenfight",
]

# Standard-Auszahlungen (werden in der DB gespeichert, per /config-set änderbar)
DEFAULT_CONFIG = {
    "payout_anfahrt": "15000",
    "payout_win":     "50000",
    "payout_loss":    "10000",
    "payout_kill":    "10000",
    "payout_assist":  "5000",
}

DB_PATH = "eventbot3000.db"
