import re
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
import config

MEDALS = ["🥇", "🥈", "🥉"]
ITEMS_PER_PAGE = 10


def _is_management(rank: int) -> bool:
    return rank >= config.MANAGEMENT_MIN_RANK


class Payouts(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._ranking_msg_id: int | None = None

    @property
    def db(self):
        return self.bot.db

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

    # ── Ranking embed helper ───────────────────────────────────────────────────

    def _build_ranking_embed(self, page: int = 1) -> tuple[discord.Embed, int]:
        all_users = self.db.get_ranking(limit=100)
        total = len(all_users)
        pages = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        page = max(1, min(page, pages))

        start = (page - 1) * ITEMS_PER_PAGE
        slice_ = all_users[start: start + ITEMS_PER_PAGE]

        e = discord.Embed(title="🏆 Live Auszahlungs-Ranking", color=discord.Color.gold())
        lines = []
        for i, u in enumerate(slice_, start=start + 1):
            medal = MEDALS[i - 1] if i <= 3 else f"{i}."
            lines.append(f"{medal} **{u['ingame_name']}** — ${u['total_payout']:,}")
        e.description = "\n".join(lines) if lines else "_Noch keine Auszahlungen._"
        e.set_footer(text=f"Seite {page}/{pages} • Automatisch sortiert")
        return e, pages

    async def _update_ranking(self):
        """Post or update the pinned ranking message in PAYOUT_CHANNEL."""
        ch = self.bot.get_channel(config.PAYOUT_CHANNEL)
        if not ch:
            return

        embed, _ = self._build_ranking_embed(1)

        # Try to edit existing message
        stored_id = self.db.cfg_get("ranking_message_id")
        if stored_id:
            try:
                msg = await ch.fetch_message(int(stored_id))
                await msg.edit(embed=embed)
                return
            except (discord.NotFound, discord.Forbidden):
                pass

        # Post new message and pin it
        msg = await ch.send(embed=embed)
        try:
            await msg.pin()
        except discord.Forbidden:
            pass
        self.db.cfg_set("ranking_message_id", str(msg.id))

    # ── /pay ───────────────────────────────────────────────────────────────────

    @app_commands.command(name="pay", description="Zahle einem User manuell einen Betrag aus")
    @app_commands.describe(
        user="Discord-User",
        amount="Betrag in $",
        reason="Grund der Auszahlung",
    )
    async def pay(self, interaction: discord.Interaction, user: discord.Member, amount: int, reason: str):
        if not await self._check_mgmt(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        target = self.db.get_user(str(user.id))
        if not target:
            await interaction.followup.send(f"❌ {user.mention} ist nicht registriert.", ephemeral=True)
            return
        if amount <= 0:
            await interaction.followup.send("❌ Betrag muss größer als 0 sein.", ephemeral=True)
            return

        self.db.record_payout(str(user.id), None, amount, reason, str(interaction.user.id))

        # Payout channel
        payout_ch = self.bot.get_channel(config.PAYOUT_CHANNEL)
        if payout_ch:
            pe = discord.Embed(title="💰 Auszahlung", color=discord.Color.gold())
            pe.add_field(name="Empfänger", value=f"{user.mention} ({target['ingame_name']})")
            pe.add_field(name="Betrag", value=f"${amount:,}")
            pe.add_field(name="Grund", value=reason, inline=False)
            pe.set_footer(text=f"Ausgezahlt von {interaction.user.display_name}")
            await payout_ch.send(embed=pe)

        # Log
        log_ch = self.bot.get_channel(config.LOG_CHANNEL)
        if log_ch:
            le = discord.Embed(title="[PAY] Manuelle Auszahlung", color=discord.Color.gold())
            le.add_field(name="Von", value=interaction.user.mention)
            le.add_field(name="An", value=user.mention)
            le.add_field(name="Betrag", value=f"${amount:,}")
            le.add_field(name="Grund", value=reason)
            await log_ch.send(embed=le)

        self.db.log("PAY", str(interaction.user.id), str(user.id), f"amount={amount} reason={reason}")
        await self._update_ranking()

        await interaction.followup.send(
            f"✅ **${amount:,}** wurden an **{target['ingame_name']}** ausgezahlt.", ephemeral=True
        )

    # ── /pay-kills ─────────────────────────────────────────────────────────────

    @app_commands.command(name="pay-kills", description="Zahle Kills/Assists für einen Spieler aus")
    @app_commands.describe(
        user="Discord-User",
        kills="Anzahl Kills",
        assists="Anzahl Assists",
        event_id="Event-ID (optional)",
    )
    async def pay_kills(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        kills: int,
        assists: int,
        event_id: int = None,
    ):
        if not await self._check_mgmt(interaction):
            return
        await interaction.response.defer(ephemeral=True)

        target = self.db.get_user(str(user.id))
        if not target:
            await interaction.followup.send(f"❌ {user.mention} ist nicht registriert.", ephemeral=True)
            return

        kill_pay   = self.db.cfg_get("payout_kill",   10000)
        assist_pay = self.db.cfg_get("payout_assist",  5000)
        amount = kills * kill_pay + assists * assist_pay

        if amount <= 0:
            await interaction.followup.send("❌ Kills und Assists müssen > 0 sein.", ephemeral=True)
            return

        reason = f"{kills}x Kill (${kill_pay:,}) + {assists}x Assist (${assist_pay:,})"
        self.db.record_payout(str(user.id), event_id, amount, reason, str(interaction.user.id))

        payout_ch = self.bot.get_channel(config.PAYOUT_CHANNEL)
        if payout_ch:
            pe = discord.Embed(title="🔫 Kill/Assist Auszahlung", color=discord.Color.gold())
            pe.add_field(name="Spieler", value=f"{user.mention} ({target['ingame_name']})")
            pe.add_field(name="Kills", value=str(kills))
            pe.add_field(name="Assists", value=str(assists))
            pe.add_field(name="Gesamt", value=f"${amount:,}")
            if event_id:
                ev = self.db.get_event(event_id)
                pe.add_field(name="Event", value=ev["event_type"] if ev else str(event_id))
            pe.set_footer(text=f"Ausgezahlt von {interaction.user.display_name}")
            await payout_ch.send(embed=pe)

        log_ch = self.bot.get_channel(config.LOG_CHANNEL)
        if log_ch:
            le = discord.Embed(title="[PAY] Kill/Assist-Auszahlung", color=discord.Color.gold())
            le.add_field(name="Von", value=interaction.user.mention)
            le.add_field(name="An", value=user.mention)
            le.add_field(name="Betrag", value=f"${amount:,}")
            le.add_field(name="Details", value=reason)
            await log_ch.send(embed=le)

        self.db.log("PAY_KILLS", str(interaction.user.id), str(user.id),
                    f"kills={kills} assists={assists} amount={amount}")
        await self._update_ranking()

        await interaction.followup.send(
            f"✅ **${amount:,}** für {kills} Kills / {assists} Assists an **{target['ingame_name']}** ausgezahlt.",
            ephemeral=True,
        )

    # ── /payout-confirm ────────────────────────────────────────────────────────

    @app_commands.command(
        name="payout-confirm",
        description="Event abschließen und alle Teilnehmer automatisch auszahlen (ab Offizier, Rang 8)",
    )
    @app_commands.describe(
        event_id="ID des Events",
        result="Ergebnis des Events",
        ausschliessen="User die KEIN Payout erhalten (@Erwähnungen, z.B. @User1 @User2)",
    )
    @app_commands.choices(result=[
        app_commands.Choice(name="Gewonnen", value="win"),
        app_commands.Choice(name="Verloren",  value="loss"),
    ])
    async def payout_confirm(
        self,
        interaction: discord.Interaction,
        event_id: int,
        result: str,
        ausschliessen: Optional[str] = None,
    ):
        if not self.bot.has_min_rank_or_admin(interaction.user, 8):
            await interaction.response.send_message(
                "❌ Nur Offizier (Rang 8+) oder Admin-Rolle dürfen Payouts bestätigen.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)

        event = self.db.get_event(event_id)
        if not event:
            await interaction.followup.send("❌ Event nicht gefunden.", ephemeral=True)
            return
        if event["status"] == "finished":
            await interaction.followup.send("⚠️ Event ist bereits abgeschlossen.", ephemeral=True)
            return

        # Parse excluded user IDs from mentions
        excluded_ids = set()
        if ausschliessen:
            for match in re.finditer(r"<@!?(\d+)>", ausschliessen):
                excluded_ids.add(match.group(1))

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
        skipped = []
        for reg in regs:
            if reg["discord_id"] in excluded_ids:
                skipped.append(reg["ingame_name"])
                continue
            self.db.record_payout(
                reg["discord_id"], event_id, total_per_player,
                reason_text, str(interaction.user.id),
            )
            paid_out.append(reg["ingame_name"])

        self.db.set_event_status(event_id, "finished")

        # Refresh event embed
        from cogs.events import _refresh_event_embed
        await _refresh_event_embed(self.bot, self.db.get_event(event_id), self.db)

        payout_ch = self.bot.get_channel(config.PAYOUT_CHANNEL)
        if payout_ch:
            pe = discord.Embed(
                title=f"💰 Event abgeschlossen – {event['event_type']}",
                color=discord.Color.gold() if result == "win" else discord.Color.light_grey(),
            )
            pe.add_field(name="Ergebnis", value="🏆 Gewonnen" if result == "win" else "💀 Verloren", inline=True)
            pe.add_field(name="Auszahlung/Spieler", value=f"${total_per_player:,}", inline=True)
            pe.add_field(name="Ausgezahlt", value=str(len(paid_out)), inline=True)
            pe.add_field(name="Ausgezahlt an", value=", ".join(paid_out) or "–", inline=False)
            if skipped:
                pe.add_field(name="❌ Kein Payout", value=", ".join(skipped), inline=False)
            pe.set_footer(text=f"Event-ID: {event_id} | Bestätigt von {interaction.user.display_name}")
            await payout_ch.send(embed=pe)

        await self._update_ranking()

        log_ch = self.bot.get_channel(config.LOG_CHANNEL)
        if log_ch:
            le = discord.Embed(title=f"[PAY] Payout-Confirm: {event['event_type']}", color=discord.Color.gold())
            le.add_field(name="Ergebnis", value=result)
            le.add_field(name="Ausgezahlt", value=str(len(paid_out)))
            le.add_field(name="Übersprungen", value=str(len(skipped)))
            le.add_field(name="Von", value=interaction.user.mention)
            await log_ch.send(embed=le)

        self.db.log("PAYOUT_CONFIRM", str(interaction.user.id), str(event_id),
                    f"result={result} paid={len(paid_out)} skipped={len(skipped)}")

        confirm = discord.Embed(title="✅ Payout bestätigt", color=discord.Color.green())
        confirm.add_field(name="Event", value=event["event_type"])
        confirm.add_field(name="Ausgezahlt", value=f"{len(paid_out)} Spieler à ${total_per_player:,}")
        if skipped:
            confirm.add_field(name="Ohne Payout", value=", ".join(skipped), inline=False)
        await interaction.followup.send(embed=confirm, ephemeral=True)

    # ── /ranking ───────────────────────────────────────────────────────────────

    @app_commands.command(name="ranking", description="Zeige das Auszahlungs-Ranking")
    @app_commands.describe(seite="Seite (Standard: 1)")
    async def ranking(self, interaction: discord.Interaction, seite: int = 1):
        embed, pages = self._build_ranking_embed(seite)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /meine-auszahlungen ────────────────────────────────────────────────────

    @app_commands.command(name="meine-auszahlungen", description="Zeige deine letzten 20 Auszahlungen")
    async def my_payouts(self, interaction: discord.Interaction):
        u = self.db.get_user(str(interaction.user.id))
        if not u:
            await interaction.response.send_message("❌ Du bist nicht registriert.", ephemeral=True)
            return

        rows = self.db.get_user_payouts(str(interaction.user.id))
        e = discord.Embed(
            title=f"💰 Auszahlungen – {u['ingame_name']}",
            color=discord.Color.gold(),
        )
        e.add_field(name="Gesamt", value=f"${u['total_payout']:,}", inline=False)

        if rows:
            lines = []
            for r in rows:
                date = r["paid_at"][:10]
                lines.append(f"`{date}` **${r['amount']:,}** — {r['reason']}")
            e.add_field(name="Letzte Auszahlungen", value="\n".join(lines[:15]), inline=False)
        else:
            e.add_field(name="Letzte Auszahlungen", value="Noch keine.", inline=False)

        await interaction.response.send_message(embed=e, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Payouts(bot))
