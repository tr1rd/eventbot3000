import re
import discord
from discord import app_commands
from discord.ext import commands, tasks
from typing import Optional
from datetime import datetime, timedelta
import config

DAY_MAP = {"mo": 0, "di": 1, "mi": 2, "do": 3, "fr": 4, "sa": 5, "so": 6}
DAY_NAMES = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _progress_bar(current: int, maximum: int, length: int = 12) -> str:
    if maximum == 0:
        return "░" * length
    filled = int((current / maximum) * length)
    return "█" * filled + "░" * (length - filled)


def _parse_deadline(deadline_str: str) -> Optional[datetime]:
    """Try to parse a deadline string as HH:MM (today). Returns None if unparseable."""
    if not deadline_str:
        return None
    try:
        t = datetime.strptime(deadline_str.strip(), "%H:%M")
        now = datetime.now()
        return t.replace(year=now.year, month=now.month, day=now.day)
    except ValueError:
        return None


def _build_event_embed(event, registrations: list, status_override: str = None,
                       schedule_label: str = None) -> discord.Embed:
    status = status_override or event["status"]
    current = len(registrations)
    maximum = event["max_players"]
    bar = _progress_bar(current, maximum)

    color = {
        "open":     discord.Color.green(),
        "closed":   discord.Color.orange(),
        "finished": discord.Color.greyple(),
    }.get(status, discord.Color.blurple())

    status_text = {
        "open":     "🟢 Aktiv",
        "closed":   "🟠 Geschlossen",
        "finished": "⚫ Abgeschlossen",
    }.get(status, status)

    e = discord.Embed(
        title=f"📋 {event['event_type']}",
        color=color,
    )
    e.add_field(name="Status", value=status_text, inline=True)
    if event["deadline"]:
        e.add_field(name="Anmeldung bis", value=f"{event['deadline']} Uhr", inline=True)
    if schedule_label:
        e.add_field(name="🔁 Zeitplan", value=schedule_label, inline=True)
    elif not event["deadline"]:
        e.add_field(name="\u200b", value="\u200b", inline=True)

    e.add_field(
        name=f"Spieler  {current}/{maximum}",
        value=f"`{bar}`",
        inline=False,
    )

    payouts = (
        f"Anfahrt : ${event['travel_pay']:,}\n"
        f"Win     : ${event['win_pay']:,}\n"
        f"Loss    : ${event['loss_pay']:,}\n"
        f"Kill    : ${event['kill_pay']:,}\n"
        f"Assist  : ${event['assist_pay']:,}"
    )
    e.add_field(name="💰 Auszahlungen", value=f"```{payouts}```", inline=True)

    if registrations:
        names = "\n".join(f"• {r['ingame_name']}" for r in registrations[:20])
        if len(registrations) > 20:
            names += f"\n_… und {len(registrations) - 20} weitere_"
        e.add_field(name="Angemeldete Spieler", value=names, inline=True)

    e.set_footer(text=f"Event-ID: {event['id']}")
    return e


# ── Persistent Button View ─────────────────────────────────────────────────────

class EventView(discord.ui.View):
    """Persistent view – survives bot restarts via custom_id."""

    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id

        btn = discord.ui.Button(
            label="✅ Anmelden",
            style=discord.ButtonStyle.green,
            custom_id=f"event_join_{event_id}",
        )
        btn.callback = self._join
        self.add_item(btn)

        btn2 = discord.ui.Button(
            label="❌ Abmelden",
            style=discord.ButtonStyle.red,
            custom_id=f"event_leave_{event_id}",
        )
        btn2.callback = self._leave
        self.add_item(btn2)

    async def _join(self, interaction: discord.Interaction):
        db = interaction.client.db
        discord_id = str(interaction.user.id)
        event = db.get_event(self.event_id)

        if not event or event["status"] != "open":
            await interaction.response.send_message(
                "⚠️ Dieses Event ist nicht mehr offen.", ephemeral=True
            )
            return

        # Deadline check
        dl = _parse_deadline(event["deadline"])
        if dl and datetime.now() >= dl:
            await interaction.response.send_message(
                "⏰ Die Anmeldefrist für dieses Event ist abgelaufen.", ephemeral=True
            )
            return

        user = db.get_user(discord_id)
        if not user:
            await interaction.response.send_message(
                "❌ Du bist nicht registriert. Nutze `/register` um dich zu registrieren.",
                ephemeral=True,
            )
            return

        if db.eventbl_check(discord_id):
            entry = db.eventbl_get(discord_id)
            await interaction.response.send_message(
                f"🚫 Du stehst auf der **Event-Blacklist** und kannst dich nicht anmelden.\n"
                f"**Grund:** {entry['reason']}\nWende dich an einen Admin.",
                ephemeral=True,
            )
            return

        if db.is_registered(self.event_id, discord_id):
            await interaction.response.send_message(
                "ℹ️ Du bist bereits für dieses Event angemeldet.", ephemeral=True
            )
            return

        count = db.registration_count(self.event_id)
        if count >= event["max_players"]:
            await interaction.response.send_message(
                "❌ Das Event ist bereits voll.", ephemeral=True
            )
            return

        db.register_for_event(self.event_id, discord_id)
        await interaction.response.send_message(
            f"✅ Du wurdest erfolgreich für **{event['event_type']}** angemeldet!", ephemeral=True
        )

        await _refresh_event_embed(interaction.client, event, db)
        db.log("EVENT_JOIN", discord_id, str(self.event_id))

    async def _leave(self, interaction: discord.Interaction):
        db = interaction.client.db
        discord_id = str(interaction.user.id)
        event = db.get_event(self.event_id)

        if not event or event["status"] != "open":
            await interaction.response.send_message(
                "⚠️ Dieses Event ist nicht mehr offen.", ephemeral=True
            )
            return

        if not db.is_registered(self.event_id, discord_id):
            await interaction.response.send_message(
                "ℹ️ Du bist nicht für dieses Event angemeldet.", ephemeral=True
            )
            return

        with db._conn() as c:
            c.execute(
                "DELETE FROM event_registrations WHERE event_id=? AND discord_id=?",
                (self.event_id, discord_id),
            )
            c.commit()

        await interaction.response.send_message(
            f"✅ Du wurdest vom Event **{event['event_type']}** abgemeldet.", ephemeral=True
        )
        await _refresh_event_embed(interaction.client, event, db)
        db.log("EVENT_LEAVE", discord_id, str(self.event_id))


async def _refresh_event_embed(bot, event, db, schedule_label: str = None):
    """Update the registration embed in the event channel."""
    if not event["message_id"]:
        return
    channel = bot.get_channel(config.EVENT_CHANNEL)
    if not channel:
        return
    try:
        msg = await channel.fetch_message(int(event["message_id"]))
        regs = db.get_event_registrations(event["id"])
        fresh_event = db.get_event(event["id"])
        embed = _build_event_embed(fresh_event, regs, schedule_label=schedule_label)
        await msg.edit(embed=embed)
    except (discord.NotFound, discord.Forbidden):
        pass


# ── Cog ────────────────────────────────────────────────────────────────────────

class Events(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    async def cog_load(self):
        self._recurring_check.start()
        self._deadline_check.start()

    async def cog_unload(self):
        self._recurring_check.cancel()
        self._deadline_check.cancel()

    # ── Deadline enforcement task ───────────────────────────────────────────────

    @tasks.loop(minutes=1)
    async def _deadline_check(self):
        now = datetime.now()
        for event in self.db.get_open_events():
            if not event["deadline"] or event["deadline_notified"]:
                continue
            dl = _parse_deadline(event["deadline"])
            if dl and now >= dl:
                self.db.set_event_status(event["id"], "closed")
                self.db.set_deadline_notified(event["id"])
                await _refresh_event_embed(self.bot, self.db.get_event(event["id"]), self.db)
                await self._send_deadline_reminder(event)

    @_deadline_check.before_loop
    async def _before_deadline(self):
        await self.bot.wait_until_ready()

    async def _send_deadline_reminder(self, event):
        regs = self.db.get_event_registrations(event["id"])
        event_ch = self.bot.get_channel(config.EVENT_CHANNEL)
        if not event_ch or not regs:
            return

        mentions = " ".join(f"<@{r['discord_id']}>" for r in regs)
        names = "\n".join(f"• {r['ingame_name']}" for r in regs)

        embed = discord.Embed(
            title=f"⏰ Anmeldeschluss – {event['event_type']}",
            description=(
                f"Die Anmeldefrist ist abgelaufen. Das Event startet bald!\n\n"
                f"⚠️ **Wer sich angemeldet hat und nicht erscheint, erhält eine Sanktion!**"
            ),
            color=discord.Color.orange(),
        )
        embed.add_field(name=f"Teilnehmer ({len(regs)})", value=names or "–", inline=False)
        embed.set_footer(text=f"Event-ID: {event['id']}")

        if event["message_id"]:
            try:
                msg = await event_ch.fetch_message(int(event["message_id"]))
                await msg.reply(content=mentions, embed=embed)
                return
            except (discord.NotFound, discord.Forbidden):
                pass
        await event_ch.send(content=mentions, embed=embed)

    # ── Recurring events task ───────────────────────────────────────────────────

    @tasks.loop(minutes=1)
    async def _recurring_check(self):
        now = datetime.now()
        for rec in self.db.get_active_recurring_events():
            should_run = False
            deadline = None

            if rec["recurrence"] == "hourly":
                run_minute = int(rec["run_at"])
                spawn_minute = (run_minute - 5) % 60
                if now.minute == spawn_minute:
                    # Compute the deadline time (5 min from now)
                    dl_hour = now.hour if spawn_minute < run_minute else (now.hour + 1) % 24
                    deadline = f"{dl_hour:02d}:{run_minute:02d}"
                    if rec["last_run"] is None:
                        should_run = True
                    else:
                        last = datetime.fromisoformat(rec["last_run"])
                        if (now - last).total_seconds() > 50 * 60:
                            should_run = True

            elif rec["recurrence"] == "daily":
                run_dt = datetime.strptime(rec["run_at"], "%H:%M")
                spawn_dt = run_dt - timedelta(minutes=5)
                if now.strftime("%H:%M") == spawn_dt.strftime("%H:%M"):
                    deadline = rec["run_at"]
                    if rec["last_run"] is None:
                        should_run = True
                    else:
                        last = datetime.fromisoformat(rec["last_run"])
                        if (now - last).total_seconds() > 23 * 3600:
                            should_run = True

            elif rec["recurrence"] == "weekly":
                w_parts = rec["run_at"].split()  # "4 20:00"
                run_weekday = int(w_parts[0])
                run_dt = datetime.strptime(w_parts[1], "%H:%M")
                spawn_dt = run_dt - timedelta(minutes=5)
                if now.weekday() == run_weekday and now.strftime("%H:%M") == spawn_dt.strftime("%H:%M"):
                    deadline = w_parts[1]
                    if rec["last_run"] is None:
                        should_run = True
                    else:
                        last = datetime.fromisoformat(rec["last_run"])
                        if (now - last).total_seconds() > 6 * 24 * 3600:
                            should_run = True

            if should_run:
                await self._spawn_recurring_event(rec, deadline=deadline)

    @_recurring_check.before_loop
    async def _before_recurring(self):
        await self.bot.wait_until_ready()

    async def _spawn_recurring_event(self, rec, deadline: str = None):
        """Create an event from a recurring template and post it to the event channel."""
        tp = rec["travel_pay"] or self.db.cfg_get("payout_anfahrt", 15000)
        wp = rec["win_pay"]    or self.db.cfg_get("payout_win",     50000)
        lp = rec["loss_pay"]   or self.db.cfg_get("payout_loss",    10000)
        kp = rec["kill_pay"]   or self.db.cfg_get("payout_kill",    10000)
        ap = rec["assist_pay"] or self.db.cfg_get("payout_assist",   5000)

        event_id = self.db.create_event(
            rec["event_type"], rec["max_players"], deadline,
            rec["created_by"], tp, wp, lp, kp, ap,
        )
        event = self.db.get_event(event_id)
        view  = EventView(event_id)
        self.bot.add_view(view)

        schedule_label = rec["schedule_label"] if rec["schedule_label"] else None
        event_ch = self.bot.get_channel(config.EVENT_CHANNEL)
        if event_ch:
            embed = _build_event_embed(event, [], schedule_label=schedule_label)
            msg = await event_ch.send(embed=embed, view=view)
            self.db.set_event_message_id(event_id, str(msg.id))

        self.db.set_recurring_last_run(rec["id"], datetime.now().isoformat(timespec="seconds"))
        self.db.log("EVENT_RECURRING_SPAWN", rec["created_by"], str(event_id),
                    f"template={rec['id']} type={rec['event_type']}")

        log_ch = self.bot.get_channel(config.LOG_CHANNEL)
        if log_ch:
            le = discord.Embed(
                title=f"[EVENT] Geplantes Event gestartet: {rec['event_type']}",
                color=discord.Color.blue(),
            )
            le.add_field(name="Template-ID", value=str(rec["id"]))
            le.add_field(name="Wiederholung", value="Stündlich" if rec["recurrence"] == "hourly" else "Täglich")
            le.add_field(name="Anmeldung bis", value=f"{deadline} Uhr" if deadline else "–")
            if schedule_label:
                le.add_field(name="Zeitplan", value=schedule_label)
            await log_ch.send(embed=le)

    async def _check_mgmt(self, interaction: discord.Interaction):
        if self.bot.has_min_rank_or_admin(interaction.user, config.MANAGEMENT_MIN_RANK):
            return True
        u = self.db.get_user(str(interaction.user.id))
        if not u:
            await interaction.response.send_message("❌ Du bist nicht registriert.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "❌ Keine Berechtigung. Nur Vize-Boss, Boss oder Admin-Rolle dürfen das.", ephemeral=True
            )
        return None

    async def _check_officer(self, interaction: discord.Interaction):
        if self.bot.has_min_rank_or_admin(interaction.user, 8):
            return True
        u = self.db.get_user(str(interaction.user.id))
        if not u:
            await interaction.response.send_message("❌ Du bist nicht registriert.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "❌ Keine Berechtigung. Nur Offizier (Rang 8+) oder Admin-Rolle dürfen das.", ephemeral=True
            )
        return None

    # ── /event-create ──────────────────────────────────────────────────────────

    @app_commands.command(name="event-create", description="Erstelle ein neues Event (ab Offizier, Rang 8)")
    @app_commands.describe(
        event_type="Art des Events (aus Liste)",
        custom_typ="Eigener Event-Typ (überschreibt die Liste)",
        max_players="Maximale Spieleranzahl",
        deadline="Anmeldeschluss im Format HH:MM (z.B. 20:00)",
        travel_pay="Anfahrtsvergütung (leer = Standard)",
        win_pay="Win-Bonus (leer = Standard)",
        loss_pay="Loss-Auszahlung (leer = Standard)",
        kill_pay="Auszahlung pro Kill (leer = Standard)",
        assist_pay="Auszahlung pro Assist (leer = Standard)",
    )
    @app_commands.choices(
        event_type=[app_commands.Choice(name=t, value=t) for t in config.EVENT_TYPES]
    )
    async def event_create(
        self,
        interaction: discord.Interaction,
        event_type: str,
        custom_typ: Optional[str] = None,
        max_players: int = 15,
        deadline: Optional[str] = None,
        travel_pay: Optional[int] = None,
        win_pay: Optional[int] = None,
        loss_pay: Optional[int] = None,
        kill_pay: Optional[int] = None,
        assist_pay: Optional[int] = None,
    ):
        if not await self._check_officer(interaction):
            return
        await interaction.response.defer()

        final_type = custom_typ.strip() if custom_typ else event_type

        # Validate deadline format
        if deadline and not _parse_deadline(deadline):
            await interaction.followup.send(
                "❌ Ungültiges Deadline-Format. Bitte HH:MM verwenden (z.B. `20:00`).", ephemeral=True
            )
            return

        tp = travel_pay  if travel_pay  is not None else self.db.cfg_get("payout_anfahrt", 15000)
        wp = win_pay     if win_pay     is not None else self.db.cfg_get("payout_win",     50000)
        lp = loss_pay    if loss_pay    is not None else self.db.cfg_get("payout_loss",    10000)
        kp = kill_pay    if kill_pay    is not None else self.db.cfg_get("payout_kill",    10000)
        ap = assist_pay  if assist_pay  is not None else self.db.cfg_get("payout_assist",   5000)

        event_id = self.db.create_event(
            final_type, max_players, deadline,
            str(interaction.user.id),
            tp, wp, lp, kp, ap,
        )
        event = self.db.get_event(event_id)
        view  = EventView(event_id)
        self.bot.add_view(view)

        embed = _build_event_embed(event, [])
        event_ch = self.bot.get_channel(config.EVENT_CHANNEL)
        if event_ch:
            msg = await event_ch.send(embed=embed, view=view)
            self.db.set_event_message_id(event_id, str(msg.id))
        else:
            await interaction.followup.send("⚠️ Event-Channel nicht gefunden.", ephemeral=True)

        confirm = discord.Embed(
            title="✅ Event erstellt",
            description=f"**{final_type}** wurde im Event-Channel gepostet.",
            color=discord.Color.green(),
        )
        confirm.add_field(name="Event-ID", value=str(event_id))
        if deadline:
            confirm.add_field(name="Anmeldeschluss", value=f"{deadline} Uhr")
        await interaction.followup.send(embed=confirm, ephemeral=True)

        log_ch = self.bot.get_channel(config.LOG_CHANNEL)
        if log_ch:
            le = discord.Embed(title=f"[EVENT] Event erstellt: {final_type}", color=discord.Color.blue())
            le.add_field(name="Erstellt von", value=interaction.user.mention)
            le.add_field(name="Event-ID", value=str(event_id))
            le.add_field(name="Max. Spieler", value=str(max_players))
            if deadline:
                le.add_field(name="Deadline", value=f"{deadline} Uhr")
            await log_ch.send(embed=le)

        self.db.log("EVENT_CREATE", str(interaction.user.id), str(event_id), final_type)

    # ── /event-close ───────────────────────────────────────────────────────────

    @app_commands.command(name="event-close", description="Schließe die Anmeldung für ein Event (ab Offizier, Rang 8)")
    @app_commands.describe(event_id="ID des Events")
    async def event_close(self, interaction: discord.Interaction, event_id: int):
        if not await self._check_officer(interaction):
            return
        event = self.db.get_event(event_id)
        if not event:
            await interaction.response.send_message("❌ Event nicht gefunden.", ephemeral=True)
            return
        if event["status"] != "open":
            await interaction.response.send_message(
                f"⚠️ Event ist bereits **{event['status']}**.", ephemeral=True
            )
            return

        self.db.set_event_status(event_id, "closed")
        await _refresh_event_embed(self.bot, self.db.get_event(event_id), self.db)

        await interaction.response.send_message(
            f"🔒 Event **{event['event_type']}** (ID: {event_id}) wurde geschlossen.", ephemeral=True
        )
        self.db.log("EVENT_CLOSE", str(interaction.user.id), str(event_id))

    # ── /event-finish ──────────────────────────────────────────────────────────

    @app_commands.command(
        name="event-finish",
        description="Schließe ein Event ab und zahle alle Teilnehmer aus (ab Offizier, Rang 8)",
    )
    @app_commands.describe(
        event_id="ID des Events",
        result="Ergebnis des Events",
    )
    @app_commands.choices(result=[
        app_commands.Choice(name="Gewonnen", value="win"),
        app_commands.Choice(name="Verloren",  value="loss"),
    ])
    async def event_finish(self, interaction: discord.Interaction, event_id: int, result: str):
        if not await self._check_officer(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        event = self.db.get_event(event_id)
        if not event:
            await interaction.followup.send("❌ Event nicht gefunden.", ephemeral=True)
            return
        if event["status"] == "finished":
            await interaction.followup.send("⚠️ Event ist bereits abgeschlossen.", ephemeral=True)
            return

        regs = self.db.get_event_registrations(event_id)
        if not regs:
            await interaction.followup.send("⚠️ Keine Anmeldungen vorhanden.", ephemeral=True)
            return

        result_pay = event["win_pay"] if result == "win" else event["loss_pay"]
        total_per_player = event["travel_pay"] + result_pay
        reason_text = (
            f"{event['event_type']} – {'Gewonnen' if result == 'win' else 'Verloren'} "
            f"(Anfahrt ${event['travel_pay']:,} + {'Win' if result == 'win' else 'Loss'} ${result_pay:,})"
        )

        paid_out = []
        for reg in regs:
            self.db.record_payout(
                reg["discord_id"], event_id, total_per_player,
                reason_text, str(interaction.user.id),
            )
            paid_out.append(reg["ingame_name"])

        self.db.set_event_status(event_id, "finished")
        await _refresh_event_embed(self.bot, self.db.get_event(event_id), self.db)

        payout_ch = self.bot.get_channel(config.PAYOUT_CHANNEL)
        if payout_ch:
            pe = discord.Embed(
                title=f"💰 Event abgeschlossen – {event['event_type']}",
                color=discord.Color.gold() if result == "win" else discord.Color.light_grey(),
            )
            pe.add_field(name="Ergebnis", value="🏆 Gewonnen" if result == "win" else "💀 Verloren", inline=True)
            pe.add_field(name="Auszahlung/Spieler", value=f"${total_per_player:,}", inline=True)
            pe.add_field(name="Teilnehmer", value=str(len(paid_out)), inline=True)
            pe.add_field(name="Ausgezahlt an", value=", ".join(paid_out) or "–", inline=False)
            pe.set_footer(text=f"Event-ID: {event_id} | Abgeschlossen von {interaction.user.display_name}")
            await payout_ch.send(embed=pe)

        await self.bot.get_cog("Payouts")._update_ranking()  # type: ignore

        log_ch = self.bot.get_channel(config.LOG_CHANNEL)
        if log_ch:
            le = discord.Embed(title=f"[EVENT] Event beendet: {event['event_type']}", color=discord.Color.gold())
            le.add_field(name="Ergebnis", value=result)
            le.add_field(name="Teilnehmer", value=str(len(paid_out)))
            le.add_field(name="Auszahlung/Spieler", value=f"${total_per_player:,}")
            le.add_field(name="Abgeschlossen von", value=interaction.user.mention)
            await log_ch.send(embed=le)

        self.db.log("EVENT_FINISH", str(interaction.user.id), str(event_id),
                    f"result={result} players={len(paid_out)} amount={total_per_player}")

        confirm = discord.Embed(title="✅ Event abgeschlossen", color=discord.Color.green())
        confirm.add_field(name="Event", value=event["event_type"])
        confirm.add_field(name="Teilnehmer ausgezahlt", value=str(len(paid_out)))
        confirm.add_field(name="Betrag/Spieler", value=f"${total_per_player:,}")
        await interaction.followup.send(embed=confirm, ephemeral=True)

    # ── /event-list ────────────────────────────────────────────────────────────

    @app_commands.command(name="event-list", description="Zeige alle offenen Events")
    async def event_list(self, interaction: discord.Interaction):
        events = self.db.get_open_events()
        if not events:
            await interaction.response.send_message(
                "📭 Aktuell gibt es keine offenen Events.", ephemeral=True
            )
            return

        e = discord.Embed(title="📋 Offene Events", color=discord.Color.blue())
        for ev in events:
            count = self.db.registration_count(ev["id"])
            e.add_field(
                name=f"[{ev['id']}] {ev['event_type']}",
                value=(
                    f"Spieler: {count}/{ev['max_players']}\n"
                    f"Anmeldeschluss: {ev['deadline'] + ' Uhr' if ev['deadline'] else 'Kein'}\n"
                    f"Anfahrt: ${ev['travel_pay']:,}"
                ),
                inline=True,
            )

        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── /event-info ────────────────────────────────────────────────────────────

    @app_commands.command(name="event-info", description="Zeige Details zu einem Event")
    @app_commands.describe(event_id="ID des Events")
    async def event_info(self, interaction: discord.Interaction, event_id: int):
        event = self.db.get_event(event_id)
        if not event:
            await interaction.response.send_message("❌ Event nicht gefunden.", ephemeral=True)
            return
        regs = self.db.get_event_registrations(event_id)
        embed = _build_event_embed(event, regs)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /event-planen ──────────────────────────────────────────────────────────

    @app_commands.command(
        name="event-planen",
        description="Plane ein sich wiederholendes Event (nur Vize-Boss / Boss)",
    )
    @app_commands.describe(
        event_type="Art des Events (aus Liste)",
        custom_typ="Eigener Event-Typ (überschreibt die Liste)",
        wiederholung="Stündlich, täglich oder wöchentlich",
        zeit="Täglich/Wöchentlich: HH:MM (z.B. 20:00) | Stündlich: Minute 0-59 (z.B. 30) | Wöchentlich: TAG HH:MM (z.B. Fr 20:00)",
        beschreibung="Angezeigter Zeitplan-Text (z.B. 'jeden Freitag um 20:00')",
        max_players="Maximale Spieleranzahl",
        travel_pay="Anfahrtsvergütung (leer = Standard)",
        win_pay="Win-Bonus (leer = Standard)",
        loss_pay="Loss-Auszahlung (leer = Standard)",
        kill_pay="Auszahlung pro Kill (leer = Standard)",
        assist_pay="Auszahlung pro Assist (leer = Standard)",
    )
    @app_commands.choices(
        event_type=[app_commands.Choice(name=t, value=t) for t in config.EVENT_TYPES],
        wiederholung=[
            app_commands.Choice(name="Stündlich",   value="hourly"),
            app_commands.Choice(name="Täglich",     value="daily"),
            app_commands.Choice(name="Wöchentlich", value="weekly"),
        ],
    )
    async def event_planen(
        self,
        interaction: discord.Interaction,
        event_type: str,
        wiederholung: str,
        zeit: str,
        custom_typ: Optional[str] = None,
        beschreibung: Optional[str] = None,
        max_players: int = 15,
        travel_pay: Optional[int] = None,
        win_pay:    Optional[int] = None,
        loss_pay:   Optional[int] = None,
        kill_pay:   Optional[int] = None,
        assist_pay: Optional[int] = None,
    ):
        if not await self._check_mgmt(interaction):
            return

        final_type = custom_typ.strip() if custom_typ else event_type

        if wiederholung == "hourly":
            if not zeit.isdigit() or not (0 <= int(zeit) <= 59):
                await interaction.response.send_message(
                    "❌ Für **stündlich** muss `zeit` eine Zahl von 0–59 sein (Minuten-Markierung).",
                    ephemeral=True,
                )
                return
            run_at = zeit.zfill(2)
            spawn_minute = (int(run_at) - 5) % 60
            zeit_display = f"Stündlich – Anmeldung ab :{spawn_minute:02d}, Start um :{run_at} Uhr"
        elif wiederholung == "weekly":
            parts = zeit.strip().split()
            if len(parts) != 2 or parts[0].lower() not in DAY_MAP:
                await interaction.response.send_message(
                    "❌ Für **wöchentlich** muss `zeit` im Format `TAG HH:MM` sein (z.B. `Fr 20:00`).\n"
                    "Gültige Tage: Mo Di Mi Do Fr Sa So",
                    ephemeral=True,
                )
                return
            try:
                datetime.strptime(parts[1], "%H:%M")
            except ValueError:
                await interaction.response.send_message(
                    "❌ Ungültiges Zeitformat. Bitte `HH:MM` verwenden (z.B. `Fr 20:00`).",
                    ephemeral=True,
                )
                return
            day_num = DAY_MAP[parts[0].lower()]
            run_at = f"{day_num} {parts[1]}"
            spawn_dt = datetime.strptime(parts[1], "%H:%M") - timedelta(minutes=5)
            zeit_display = f"Wöchentlich {DAY_NAMES[day_num]} – Anmeldung ab {spawn_dt.strftime('%H:%M')}, Start um {parts[1]} Uhr"
        else:
            try:
                datetime.strptime(zeit, "%H:%M")
            except ValueError:
                await interaction.response.send_message(
                    "❌ Für **täglich** muss `zeit` im Format HH:MM sein (z.B. `20:00`).",
                    ephemeral=True,
                )
                return
            run_at = zeit
            spawn_dt = datetime.strptime(run_at, "%H:%M") - timedelta(minutes=5)
            zeit_display = f"Täglich – Anmeldung ab {spawn_dt.strftime('%H:%M')}, Start um {run_at} Uhr"

        schedule_label = beschreibung or zeit_display

        rec_id = self.db.create_recurring_event(
            final_type, max_players, wiederholung, run_at,
            travel_pay, win_pay, loss_pay, kill_pay, assist_pay,
            str(interaction.user.id),
            schedule_label=schedule_label,
        )

        e = discord.Embed(title="✅ Event geplant", color=discord.Color.green())
        e.add_field(name="Event-Typ",     value=final_type)
        e.add_field(name="Wiederholung",  value="Stündlich" if wiederholung == "hourly" else "Täglich")
        e.add_field(name="Zeitplan",      value=schedule_label)
        e.add_field(name="Max. Spieler",  value=str(max_players))
        e.add_field(name="Template-ID",   value=str(rec_id))
        e.set_footer(text="Anmeldezeit öffnet 5 Minuten vor dem Start automatisch.")
        await interaction.response.send_message(embed=e, ephemeral=True)

        self.db.log("EVENT_PLAN_CREATE", str(interaction.user.id), str(rec_id),
                    f"type={final_type} recurrence={wiederholung} run_at={run_at}")

    # ── /event-planung-liste ───────────────────────────────────────────────────

    @app_commands.command(
        name="event-planung-liste",
        description="Zeige alle aktiven Event-Planungen (nur Vize-Boss / Boss)",
    )
    async def event_planung_liste(self, interaction: discord.Interaction):
        if not await self._check_mgmt(interaction):
            return

        recs = self.db.get_active_recurring_events()
        if not recs:
            await interaction.response.send_message(
                "📭 Keine aktiven Event-Planungen vorhanden.", ephemeral=True
            )
            return

        e = discord.Embed(title="📅 Aktive Event-Planungen", color=discord.Color.blue())
        for rec in recs:
            if rec["recurrence"] == "hourly":
                run_min = int(rec["run_at"])
                spawn_min = (run_min - 5) % 60
                zeitplan = f"Stündlich – Anmeldung :{spawn_min:02d}, Start :{rec['run_at']} Uhr"
            elif rec["recurrence"] == "weekly":
                w_parts = rec["run_at"].split()
                day_name = DAY_NAMES[int(w_parts[0])]
                run_dt = datetime.strptime(w_parts[1], "%H:%M")
                spawn_dt = run_dt - timedelta(minutes=5)
                zeitplan = f"Wöchentlich {day_name} – Anmeldung {spawn_dt.strftime('%H:%M')}, Start {w_parts[1]} Uhr"
            else:
                run_dt = datetime.strptime(rec["run_at"], "%H:%M")
                spawn_dt = run_dt - timedelta(minutes=5)
                zeitplan = f"Täglich – Anmeldung {spawn_dt.strftime('%H:%M')}, Start {rec['run_at']} Uhr"
            last = rec["last_run"][:16].replace("T", " ") if rec["last_run"] else "Noch nie"
            label = rec["schedule_label"] or zeitplan
            e.add_field(
                name=f"[{rec['id']}] {rec['event_type']}",
                value=(
                    f"📋 {label}\n"
                    f"👥 Max. {rec['max_players']} Spieler\n"
                    f"🕐 Zuletzt: {last}"
                ),
                inline=True,
            )

        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── /event-planung-stoppen ─────────────────────────────────────────────────

    @app_commands.command(
        name="event-planung-stoppen",
        description="Stoppe eine geplante Event-Wiederholung (ab Offizier, Rang 8)",
    )
    @app_commands.describe(template_id="Template-ID der Planung (aus /event-planung-liste)")
    async def event_planung_stoppen(self, interaction: discord.Interaction, template_id: int):
        if not await self._check_officer(interaction):
            return

        ok = self.db.deactivate_recurring_event(template_id)
        if not ok:
            await interaction.response.send_message(
                f"❌ Template-ID `{template_id}` nicht gefunden oder bereits inaktiv.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ Event-Planung `{template_id}` wurde gestoppt.", ephemeral=True
        )
        self.db.log("EVENT_PLAN_STOP", str(interaction.user.id), str(template_id))


async def setup(bot: commands.Bot):
    await bot.add_cog(Events(bot))
