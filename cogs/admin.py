import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import config


def _is_rank_role(name: str) -> bool:
    parts = name.split(" | ", 1)
    return len(parts) == 2 and parts[0].isdigit()

DEFAULT_RANK_COLORS = {
    1:  0x95a5a6,
    2:  0x7f8c8d,
    3:  0x27ae60,
    4:  0x2980b9,
    5:  0x8e44ad,
    6:  0xf39c12,
    7:  0xe67e22,
    8:  0xe74c3c,
    9:  0xc0392b,
    10: 0xf1c40f,
}

VALID_CONFIG_KEYS = [
    "payout_anfahrt",
    "payout_win",
    "payout_loss",
    "payout_kill",
    "payout_assist",
]


def _is_management(rank: int) -> bool:
    return rank >= config.MANAGEMENT_MIN_RANK


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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

    # ── /admin-rolle-setzen ────────────────────────────────────────────────────

    @app_commands.command(
        name="admin-rolle-setzen",
        description="Setze die Admin-Rolle (Ersteinrichtung: jeder; danach nur Admin/Management)",
    )
    @app_commands.describe(rolle="Discord-Rolle mit vollem Admin-Zugriff")
    async def admin_rolle_setzen(self, interaction: discord.Interaction, rolle: discord.Role):
        existing_id = self.db.cfg_get("admin_role_id")

        # Bootstrap: falls noch keine Admin-Rolle gesetzt ist, darf es jeder
        if existing_id is not None:
            if not self.bot.has_min_rank_or_admin(interaction.user, config.MANAGEMENT_MIN_RANK):
                await interaction.response.send_message(
                    "❌ Die Admin-Rolle ist bereits gesetzt. Nur bestehende Admins oder Management können sie ändern.",
                    ephemeral=True,
                )
                return

        self.db.cfg_set("admin_role_id", str(rolle.id))

        e = discord.Embed(
            title="✅ Admin-Rolle gesetzt",
            description=f"**{rolle.mention}** hat jetzt vollen Management-Zugriff auf alle Bot-Commands.",
            color=discord.Color.green(),
        )
        if existing_id is None:
            e.set_footer(text="Ersteinrichtung – diese Aktion wurde einmalig für jeden freigegeben.")
        await interaction.response.send_message(embed=e)

        log_ch = self.bot.get_channel(config.LOG_CHANNEL)
        if log_ch:
            le = discord.Embed(title="[ADMIN] Admin-Rolle geändert", color=discord.Color.orange())
            le.add_field(name="Neue Rolle", value=rolle.mention)
            le.add_field(name="Gesetzt von", value=interaction.user.mention)
            le.add_field(name="Bootstrap", value="Ja" if existing_id is None else "Nein")
            await log_ch.send(embed=le)

        self.db.log("ADMIN_ROLE_SET", str(interaction.user.id), str(rolle.id))

    # ── /rang-setzen ───────────────────────────────────────────────────────────

    @app_commands.command(name="rang-setzen", description="Setze den Rang eines Users (nur Management)")
    @app_commands.describe(user="Discord-User", rang="Rang 0–10")
    async def rang_setzen(self, interaction: discord.Interaction, user: discord.Member, rang: int):
        if not await self._check_mgmt(interaction):
            return

        if rang < 0 or rang > 10:
            await interaction.response.send_message(
                "❌ Rang muss zwischen 0 und 10 liegen.", ephemeral=True
            )
            return

        target = self.db.get_user(str(user.id))
        if not target:
            await interaction.response.send_message(
                f"❌ {user.mention} ist nicht registriert.", ephemeral=True
            )
            return

        old_rank = target["rank"]
        self.db.update_user_rank(str(user.id), rang)

        # Update Discord roles using DB role names from /rang-setup
        if interaction.guild:
            role_name = self.db.cfg_get_str(f"rank_role_{rang}")
            new_role  = discord.utils.get(interaction.guild.roles, name=role_name) if role_name else None
            old_roles = [r for r in user.roles if _is_rank_role(r.name)]
            try:
                await user.remove_roles(*old_roles, reason="Rang-Update")
                if new_role:
                    await user.add_roles(new_role, reason="Rang-Update")
            except discord.Forbidden:
                pass

        await interaction.response.send_message(
            f"✅ **{target['ingame_name']}** erhält Rang **{config.RANKS[rang]}** (Rang {rang}).",
            ephemeral=True,
        )

        log_ch = self.bot.get_channel(config.LOG_CHANNEL)
        if log_ch:
            le = discord.Embed(title="[ROLE] Rang geändert", color=discord.Color.blue())
            le.add_field(name="User", value=user.mention)
            le.add_field(name="Von", value=f"{config.RANKS[old_rank]} ({old_rank})")
            le.add_field(name="Auf", value=f"{config.RANKS[rang]} ({rang})")
            le.add_field(name="Geändert von", value=interaction.user.mention)
            await log_ch.send(embed=le)

        self.db.log("RANK_SET", str(interaction.user.id), str(user.id),
                    f"old={old_rank} new={rang}")

    # ── /rang-setup ────────────────────────────────────────────────────────────

    @app_commands.command(
        name="rang-setup",
        description="Erstelle das Rang-System interaktiv (Rang 1–10)",
    )
    async def rang_setup(self, interaction: discord.Interaction):
        if not await self._check_mgmt(interaction):
            return
        if not interaction.guild:
            await interaction.response.send_message("❌ Kein Guild-Kontext.", ephemeral=True)
            return

        channel = interaction.channel
        user    = interaction.user

        await interaction.response.send_message(
            "🎭 **Rang-Setup gestartet!**\n"
            "Ich frage dich jetzt nach den Namen für Rang 1–10.\n"
            "Antworte mit dem **Namen** (ohne Nummer), optional gefolgt von einer Farbe: `Name #RRGGBB`\n"
            "Ohne Farbe wird eine Standardfarbe verwendet. Tippe `abbrechen` zum Abbrechen.",
        )

        created = []
        skipped = []

        for rank_num in range(1, 11):
            prompt_msg = await channel.send(f"➡️ **Rang {rank_num}** | `{rank_num} | `...")

            def check(m: discord.Message):
                return m.author.id == user.id and m.channel.id == channel.id

            try:
                reply = await self.bot.wait_for("message", check=check, timeout=60.0)
            except asyncio.TimeoutError:
                await channel.send("⏰ Timeout – Setup abgebrochen.")
                return

            if reply.content.strip().lower() == "abbrechen":
                await channel.send("❌ Setup abgebrochen.")
                return

            # Parse optional color: "Name #RRGGBB"
            parts = reply.content.strip().split()
            color_val = DEFAULT_RANK_COLORS[rank_num]
            if parts and parts[-1].startswith("#") and len(parts[-1]) == 7:
                try:
                    color_val = int(parts[-1][1:], 16)
                    parts = parts[:-1]
                except ValueError:
                    pass
            display_name = " ".join(parts) if parts else str(rank_num)
            role_name = f"{rank_num} | {display_name}"

            # Delete user reply for cleaner look
            try:
                await reply.delete()
            except discord.Forbidden:
                pass

            # Create role with color
            existing = discord.utils.get(interaction.guild.roles, name=role_name)
            if existing:
                await prompt_msg.edit(content=f"⚠️ `{role_name}` existiert bereits — übersprungen.")
                skipped.append(role_name)
            else:
                try:
                    await interaction.guild.create_role(
                        name=role_name,
                        color=discord.Color(color_val),
                        permissions=discord.Permissions.none(),
                        reason="EventBot3000 Rang-Setup",
                    )
                    await prompt_msg.edit(content=f"✅ `{role_name}` erstellt.")
                    created.append(role_name)
                except discord.Forbidden:
                    await channel.send("❌ Fehlende Berechtigung zum Erstellen von Rollen. Abbruch.")
                    return

            # Store in DB
            self.db.cfg_set(f"rank_role_{rank_num}", role_name)

        e = discord.Embed(title="🎉 Rang-Setup abgeschlossen", color=discord.Color.green())
        if created:
            e.add_field(name="Erstellt", value="\n".join(created), inline=False)
        if skipped:
            e.add_field(name="Übersprungen", value="\n".join(skipped), inline=False)
        await channel.send(embed=e)
        self.db.log("RANG_SETUP", str(user.id), details=f"created={len(created)}")

    # ── /config-set ────────────────────────────────────────────────────────────

    @app_commands.command(name="config-set", description="Ändere eine Bot-Konfiguration")
    @app_commands.describe(
        key="Konfigurations-Schlüssel",
        value="Neuer Wert",
    )
    @app_commands.choices(
        key=[app_commands.Choice(name=k, value=k) for k in VALID_CONFIG_KEYS]
    )
    async def config_set(self, interaction: discord.Interaction, key: str, value: int):
        if not await self._check_mgmt(interaction):
            return

        self.db.cfg_set(key, str(value))
        await interaction.response.send_message(
            f"✅ `{key}` wurde auf **${value:,}** gesetzt.", ephemeral=True
        )
        self.db.log("CONFIG_SET", str(interaction.user.id), details=f"{key}={value}")

    # ── /config-list ───────────────────────────────────────────────────────────

    @app_commands.command(name="config-list", description="Zeige die aktuelle Bot-Konfiguration")
    async def config_list(self, interaction: discord.Interaction):
        if not await self._check_mgmt(interaction):
            return

        rows = self.db.cfg_get_all()
        e = discord.Embed(title="⚙️ Bot-Konfiguration", color=discord.Color.blurple())
        for row in rows:
            if row["key"].startswith("payout_"):
                label = row["key"].replace("payout_", "").capitalize()
                try:
                    e.add_field(name=label, value=f"${int(row['value']):,}", inline=True)
                except ValueError:
                    e.add_field(name=label, value=row["value"], inline=True)
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── /user-liste ────────────────────────────────────────────────────────────

    @app_commands.command(name="user-liste", description="Alle registrierten User anzeigen")
    @app_commands.describe(seite="Seite (Standard: 1)")
    async def user_liste(self, interaction: discord.Interaction, seite: int = 1):
        if not await self._check_mgmt(interaction):
            return

        users = self.db.get_all_users()
        if not users:
            await interaction.response.send_message("📭 Keine User registriert.", ephemeral=True)
            return

        items_per_page = 15
        pages = max(1, (len(users) + items_per_page - 1) // items_per_page)
        seite = max(1, min(seite, pages))
        start = (seite - 1) * items_per_page
        slice_ = users[start: start + items_per_page]

        e = discord.Embed(title="👥 Registrierte User", color=discord.Color.blurple())
        lines = []
        for u in slice_:
            rank_name = config.RANKS.get(u["rank"], "?")
            lines.append(f"**{u['ingame_name']}** (ID: `{u['ingame_id']}`) — {rank_name}")
        e.description = "\n".join(lines)
        e.set_footer(text=f"Seite {seite}/{pages} • {len(users)} User gesamt")
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ── /bl-check ──────────────────────────────────────────────────────────────

    @app_commands.command(name="bl-check", description="Prüfe einen User auf allen Blacklists")
    @app_commands.describe(user="Discord-User (optional)", ingame_id="Ingame-ID (optional)")
    async def bl_check(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None,
        ingame_id: str = None,
    ):
        if not user and not ingame_id:
            await interaction.response.send_message(
                "❌ Gib entweder einen Discord-User oder eine Ingame-ID an.", ephemeral=True
            )
            return

        e = discord.Embed(title="🔍 Blacklist-Check", color=discord.Color.blurple())

        if ingame_id:
            fam_entry = self.db.fambl_get_by_id(ingame_id)
            if fam_entry:
                e.add_field(
                    name="🚫 Fam-Blacklist",
                    value=f"**{fam_entry['ingame_name']}** — {fam_entry['reason']}",
                    inline=False,
                )
            else:
                e.add_field(name="✅ Fam-Blacklist", value="Nicht gelistet", inline=False)

        if user:
            event_entry = self.db.eventbl_get(str(user.id))
            if event_entry:
                e.add_field(
                    name="🚫 Event-Blacklist",
                    value=f"{user.mention} — {event_entry['reason']}",
                    inline=False,
                )
            else:
                e.add_field(name="✅ Event-Blacklist", value="Nicht gelistet", inline=False)

        await interaction.response.send_message(embed=e, ephemeral=True)


    # ── /commands ──────────────────────────────────────────────────────────────

    @app_commands.command(name="commands", description="Zeige alle verfügbaren Commands")
    async def commands_list(self, interaction: discord.Interaction):
        u = self.db.get_user(str(interaction.user.id))
        rank = self.bot.get_effective_rank(interaction.user)
        is_mgmt = rank >= config.MANAGEMENT_MIN_RANK
        is_reg  = rank >= 7

        e = discord.Embed(
            title="📋 EventBot3000 – Command-Übersicht",
            color=discord.Color.blurple(),
        )

        admin_role_set = self.db.cfg_get("admin_role_id") is not None
        if not admin_role_set:
            e.add_field(
                name="⚠️ Ersteinrichtung",
                value="`/admin-rolle-setzen <rolle>` — Admin-Rolle festlegen (einmalig für jeden nutzbar)",
                inline=False,
            )

        e.add_field(
            name="👤 Allgemein",
            value=(
                "`/profil [user]` — Profil anzeigen\n"
                "`/meine-auszahlungen` — Eigene Auszahlungshistorie\n"
                "`/ranking [seite]` — Auszahlungs-Ranking\n"
                "`/commands` — Diese Übersicht"
            ),
            inline=False,
        )

        if is_reg:
            e.add_field(
                name=f"📝 Registrierung (ab Rang 7)",
                value=(
                    "`/register <user> <vorname> <nachname> <id>` — User registrieren"
                ),
                inline=False,
            )

        if is_mgmt:
            e.add_field(
                name="📋 Events (Vize-Boss / Boss)",
                value=(
                    "`/event-create <typ> [custom_typ] ...` — Event erstellen\n"
                    "`/event-close <id>` — Anmeldung schließen\n"
                    "`/event-finish <id> <win/loss>` — Event abschließen & auszahlen\n"
                    "`/event-list` — Offene Events\n"
                    "`/event-info <id>` — Event-Details\n"
                    "`/event-planen <typ> <täglich/stündlich> <zeit>` — Wiederkehrendes Event planen\n"
                    "`/event-planung-liste` — Alle aktiven Planungen\n"
                    "`/event-planung-stoppen <id>` — Planung stoppen"
                ),
                inline=False,
            )

            e.add_field(
                name="💰 Auszahlungen",
                value=(
                    "`/payout-confirm <id> <win/loss> [ausschliessen]` — Event-Payout bestätigen (Rang 8+)\n"
                    "`/pay <user> <betrag> <grund>` — Manuelle Auszahlung\n"
                    "`/pay-kills <user> <kills> <assists> [event_id]` — Kill/Assist Auszahlung"
                ),
                inline=False,
            )

            e.add_field(
                name="🚫 Blacklists (Vize-Boss / Boss)",
                value=(
                    "`/fambl-add/remove/check/list` — Fam-Blacklist\n"
                    "`/eventbl-add/remove/check/list` — Event-Blacklist\n"
                    "`/bl-check [user] [ingame_id]` — Beide Blacklists prüfen"
                ),
                inline=False,
            )

            e.add_field(
                name="⚙️ Admin (Vize-Boss / Boss)",
                value=(
                    "`/admin-rolle-setzen <rolle>` — Admin-Rolle festlegen (Ersteinrichtung)\n"
                    "`/rang-setzen <user> <rang>` — Rang vergeben\n"
                    "`/rang-setup` — Rang-Rollen erstellen (einmalig)\n"
                    "`/config-set <key> <wert>` — Auszahlung konfigurieren\n"
                    "`/config-list` — Konfiguration anzeigen\n"
                    "`/user-liste [seite]` — Alle registrierten User"
                ),
                inline=False,
            )

        rank_label = f"{config.RANKS.get(rank, 'Gast')} (Rang {rank})"
        e.set_footer(text=f"Dein Rang: {rank_label} • Nur für dich sichtbar")
        await interaction.response.send_message(embed=e, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
