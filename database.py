import sqlite3
from config import DB_PATH, DEFAULT_CONFIG


class Database:
    def __init__(self):
        self._init_db()

    def _conn(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self):
        with self._conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    discord_id   TEXT PRIMARY KEY,
                    ingame_name  TEXT NOT NULL,
                    ingame_id    TEXT NOT NULL UNIQUE,
                    rank         INTEGER DEFAULT 1,
                    total_payout INTEGER DEFAULT 0,
                    joined_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS events (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type   TEXT    NOT NULL,
                    max_players  INTEGER NOT NULL DEFAULT 15,
                    deadline     TEXT,
                    status       TEXT    NOT NULL DEFAULT 'open',
                    created_by   TEXT,
                    message_id   TEXT,
                    travel_pay   INTEGER,
                    win_pay      INTEGER,
                    loss_pay     INTEGER,
                    kill_pay     INTEGER,
                    assist_pay   INTEGER,
                    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS event_registrations (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id     INTEGER NOT NULL,
                    discord_id   TEXT    NOT NULL,
                    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (event_id, discord_id),
                    FOREIGN KEY (event_id)   REFERENCES events(id),
                    FOREIGN KEY (discord_id) REFERENCES users(discord_id)
                );

                CREATE TABLE IF NOT EXISTS payouts (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    discord_id TEXT,
                    event_id   INTEGER,
                    amount     INTEGER,
                    reason     TEXT,
                    paid_by    TEXT,
                    paid_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS famblacklist (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ingame_name TEXT,
                    ingame_id   TEXT UNIQUE,
                    reason      TEXT,
                    added_by    TEXT,
                    added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS eventblacklist (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    discord_id  TEXT UNIQUE,
                    ingame_name TEXT,
                    reason      TEXT,
                    added_by    TEXT,
                    added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS config (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS logs (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    action    TEXT,
                    actor_id  TEXT,
                    target_id TEXT,
                    details   TEXT,
                    ts        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS recurring_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type  TEXT    NOT NULL,
                    max_players INTEGER NOT NULL DEFAULT 15,
                    recurrence  TEXT    NOT NULL,
                    run_at      TEXT    NOT NULL,
                    travel_pay  INTEGER,
                    win_pay     INTEGER,
                    loss_pay    INTEGER,
                    kill_pay    INTEGER,
                    assist_pay  INTEGER,
                    created_by  TEXT,
                    active      INTEGER DEFAULT 1,
                    last_run    TIMESTAMP,
                    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Seed default config values
            for k, v in DEFAULT_CONFIG.items():
                c.execute("INSERT OR IGNORE INTO config (key,value) VALUES (?,?)", (k, v))
            c.commit()

        # Migrations: add columns added after initial schema
        for sql in [
            "ALTER TABLE events ADD COLUMN deadline_notified INTEGER DEFAULT 0",
            "ALTER TABLE recurring_events ADD COLUMN schedule_label TEXT",
        ]:
            try:
                with self._conn() as c:
                    c.execute(sql)
                    c.commit()
            except Exception:
                pass  # column already exists

    # ── Users ──────────────────────────────────────────────────────────────────

    def register_user(self, discord_id: str, ingame_name: str, ingame_id: str) -> bool:
        try:
            with self._conn() as c:
                c.execute(
                    "INSERT INTO users (discord_id,ingame_name,ingame_id) VALUES (?,?,?)",
                    (discord_id, ingame_name, ingame_id),
                )
                c.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_user(self, discord_id: str):
        with self._conn() as c:
            return c.execute("SELECT * FROM users WHERE discord_id=?", (discord_id,)).fetchone()

    def get_user_by_ingame_id(self, ingame_id: str):
        with self._conn() as c:
            return c.execute("SELECT * FROM users WHERE ingame_id=?", (ingame_id,)).fetchone()

    def update_user_rank(self, discord_id: str, rank: int):
        with self._conn() as c:
            c.execute("UPDATE users SET rank=? WHERE discord_id=?", (rank, discord_id))
            c.commit()

    def add_to_total_payout(self, discord_id: str, amount: int):
        with self._conn() as c:
            c.execute(
                "UPDATE users SET total_payout=total_payout+? WHERE discord_id=?",
                (amount, discord_id),
            )
            c.commit()

    def get_ranking(self, limit: int = 10):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM users ORDER BY total_payout DESC LIMIT ?", (limit,)
            ).fetchall()

    def get_all_users(self):
        with self._conn() as c:
            return c.execute("SELECT * FROM users ORDER BY rank DESC, ingame_name").fetchall()

    # ── Events ─────────────────────────────────────────────────────────────────

    def create_event(self, event_type, max_players, deadline, created_by,
                     travel_pay, win_pay, loss_pay, kill_pay, assist_pay) -> int:
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO events
                   (event_type,max_players,deadline,created_by,
                    travel_pay,win_pay,loss_pay,kill_pay,assist_pay)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (event_type, max_players, deadline, created_by,
                 travel_pay, win_pay, loss_pay, kill_pay, assist_pay),
            )
            c.commit()
            return cur.lastrowid

    def get_event(self, event_id: int):
        with self._conn() as c:
            return c.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()

    def get_open_events(self):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM events WHERE status='open' ORDER BY created_at DESC"
            ).fetchall()

    def set_event_message_id(self, event_id: int, message_id: str):
        with self._conn() as c:
            c.execute("UPDATE events SET message_id=? WHERE id=?", (message_id, event_id))
            c.commit()

    def set_event_status(self, event_id: int, status: str):
        with self._conn() as c:
            c.execute("UPDATE events SET status=? WHERE id=?", (status, event_id))
            c.commit()

    def set_deadline_notified(self, event_id: int):
        with self._conn() as c:
            c.execute("UPDATE events SET deadline_notified=1 WHERE id=?", (event_id,))
            c.commit()

    # ── Event Registrations ────────────────────────────────────────────────────

    def register_for_event(self, event_id: int, discord_id: str) -> bool:
        try:
            with self._conn() as c:
                c.execute(
                    "INSERT INTO event_registrations (event_id,discord_id) VALUES (?,?)",
                    (event_id, discord_id),
                )
                c.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_event_registrations(self, event_id: int):
        with self._conn() as c:
            return c.execute(
                """SELECT er.*, u.ingame_name, u.ingame_id, u.rank
                   FROM event_registrations er
                   JOIN users u ON er.discord_id=u.discord_id
                   WHERE er.event_id=?
                   ORDER BY er.registered_at""",
                (event_id,),
            ).fetchall()

    def registration_count(self, event_id: int) -> int:
        with self._conn() as c:
            return c.execute(
                "SELECT COUNT(*) FROM event_registrations WHERE event_id=?", (event_id,)
            ).fetchone()[0]

    def is_registered(self, event_id: int, discord_id: str) -> bool:
        with self._conn() as c:
            return c.execute(
                "SELECT 1 FROM event_registrations WHERE event_id=? AND discord_id=?",
                (event_id, discord_id),
            ).fetchone() is not None

    # ── Payouts ────────────────────────────────────────────────────────────────

    def record_payout(self, discord_id: str, event_id, amount: int, reason: str, paid_by: str):
        with self._conn() as c:
            c.execute(
                "INSERT INTO payouts (discord_id,event_id,amount,reason,paid_by) VALUES (?,?,?,?,?)",
                (discord_id, event_id, amount, reason, paid_by),
            )
            c.commit()
        self.add_to_total_payout(discord_id, amount)

    def get_user_payouts(self, discord_id: str):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM payouts WHERE discord_id=? ORDER BY paid_at DESC LIMIT 20",
                (discord_id,),
            ).fetchall()

    # ── Fam-Blacklist ──────────────────────────────────────────────────────────

    def fambl_add(self, ingame_name: str, ingame_id: str, reason: str, added_by: str) -> bool:
        try:
            with self._conn() as c:
                c.execute(
                    "INSERT INTO famblacklist (ingame_name,ingame_id,reason,added_by) VALUES (?,?,?,?)",
                    (ingame_name, ingame_id, reason, added_by),
                )
                c.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def fambl_remove(self, ingame_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM famblacklist WHERE ingame_id=?", (ingame_id,))
            c.commit()
            return cur.rowcount > 0

    def fambl_check(self, ingame_id: str) -> bool:
        with self._conn() as c:
            return c.execute(
                "SELECT 1 FROM famblacklist WHERE ingame_id=?", (ingame_id,)
            ).fetchone() is not None

    def fambl_get_all(self):
        with self._conn() as c:
            return c.execute("SELECT * FROM famblacklist ORDER BY added_at DESC").fetchall()

    def fambl_get_by_id(self, ingame_id: str):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM famblacklist WHERE ingame_id=?", (ingame_id,)
            ).fetchone()

    # ── Event-Blacklist ────────────────────────────────────────────────────────

    def eventbl_add(self, discord_id: str, ingame_name: str, reason: str, added_by: str) -> bool:
        try:
            with self._conn() as c:
                c.execute(
                    "INSERT INTO eventblacklist (discord_id,ingame_name,reason,added_by) VALUES (?,?,?,?)",
                    (discord_id, ingame_name, reason, added_by),
                )
                c.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def eventbl_remove(self, discord_id: str) -> bool:
        with self._conn() as c:
            cur = c.execute("DELETE FROM eventblacklist WHERE discord_id=?", (discord_id,))
            c.commit()
            return cur.rowcount > 0

    def eventbl_check(self, discord_id: str) -> bool:
        with self._conn() as c:
            return c.execute(
                "SELECT 1 FROM eventblacklist WHERE discord_id=?", (discord_id,)
            ).fetchone() is not None

    def eventbl_get_all(self):
        with self._conn() as c:
            return c.execute("SELECT * FROM eventblacklist ORDER BY added_at DESC").fetchall()

    def eventbl_get(self, discord_id: str):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM eventblacklist WHERE discord_id=?", (discord_id,)
            ).fetchone()

    # ── Config ─────────────────────────────────────────────────────────────────

    def cfg_get(self, key: str, default=None):
        with self._conn() as c:
            row = c.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
            return int(row[0]) if row else default

    def cfg_get_str(self, key: str, default=None):
        with self._conn() as c:
            row = c.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
            return row[0] if row else default

    def cfg_set(self, key: str, value: str):
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO config (key,value) VALUES (?,?)", (key, value))
            c.commit()

    def cfg_get_all(self):
        with self._conn() as c:
            return c.execute("SELECT * FROM config ORDER BY key").fetchall()

    # ── Recurring Events ───────────────────────────────────────────────────────

    def create_recurring_event(self, event_type, max_players, recurrence, run_at,
                                travel_pay, win_pay, loss_pay, kill_pay, assist_pay,
                                created_by, schedule_label=None) -> int:
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO recurring_events
                   (event_type, max_players, recurrence, run_at,
                    travel_pay, win_pay, loss_pay, kill_pay, assist_pay, created_by, schedule_label)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (event_type, max_players, recurrence, run_at,
                 travel_pay, win_pay, loss_pay, kill_pay, assist_pay, created_by, schedule_label),
            )
            c.commit()
            return cur.lastrowid

    def get_active_recurring_events(self):
        with self._conn() as c:
            return c.execute(
                "SELECT * FROM recurring_events WHERE active=1 ORDER BY created_at"
            ).fetchall()

    def set_recurring_last_run(self, rec_id: int, ts: str):
        with self._conn() as c:
            c.execute("UPDATE recurring_events SET last_run=? WHERE id=?", (ts, rec_id))
            c.commit()

    def deactivate_recurring_event(self, rec_id: int) -> bool:
        with self._conn() as c:
            cur = c.execute("UPDATE recurring_events SET active=0 WHERE id=?", (rec_id,))
            c.commit()
            return cur.rowcount > 0

    # ── Logs ───────────────────────────────────────────────────────────────────

    def log(self, action: str, actor_id: str, target_id: str = None, details: str = None):
        with self._conn() as c:
            c.execute(
                "INSERT INTO logs (action,actor_id,target_id,details) VALUES (?,?,?,?)",
                (action, actor_id, target_id, details),
            )
            c.commit()
