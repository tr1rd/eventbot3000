import discord
from discord import app_commands
from discord.ext import commands
import config

REGISTER_MIN_RANK = 7  # Hauptmann und höher dürfen registrieren


def rank_label(rank: int) -> str:
    return f"{config.RANKS.get(rank, '?')} (Rang {rank})"


def _is_rank_role(name: str) -> bool:
    """Returns True if the role name matches the 'N | ...' pattern."""
    parts = name.split(" | ", 1)
    return len(parts) == 2 and parts[0].isdigit()


class Registration(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    # ── /register ─────────────────────────────────────────────────────────────

    @app_commands.command(
        name="register",
        description="Registriere einen User (nur ab Rang 7)"
    )
    @app_commands.describe(
        user="Der Discord-User der registriert werden soll",
        vorname="Ingame-Vorname",
        nachname="Ingame-Nachname",
        ingame_id="Ingame-ID (z.B. 12345)",
    )
    async def register(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        vorname: str,
        nachname: str,
        ingame_id: str,
    ):
        await interaction.response.defer(ephemeral=True)

        # Permission check
        if not self.bot.has_min_rank_or_admin(interaction.user, REGISTER_MIN_RANK):
            e = discord.Embed(
                title="❌ Keine Berechtigung",
                description=f"Nur Mitglieder ab **{config.RANKS[REGISTER_MIN_RANK]}** (Rang {REGISTER_MIN_RANK}) oder mit Admin-Rolle dürfen User registrieren.",
                color=discord.Color.red(),
            )
            await interaction.followup.send(embed=e, ephemeral=True)
            return

        discord_id = str(user.id)
        ingame_name = f"{vorname} {nachname}"

        # Already registered?
        if self.db.get_user(discord_id):
            existing = self.db.get_user(discord_id)
            e = discord.Embed(
                title="❌ Bereits registriert",
                description=f"{user.mention} ist bereits als **{existing['ingame_name']}** (ID: `{existing['ingame_id']}`) registriert.",
                color=discord.Color.red(),
            )
            await interaction.followup.send(embed=e, ephemeral=True)
            return

        # Ingame-ID already in use?
        if self.db.get_user_by_ingame_id(ingame_id):
            e = discord.Embed(
                title="❌ ID bereits vergeben",
                description="Diese Ingame-ID ist bereits mit einem anderen Discord-Account verknüpft.",
                color=discord.Color.red(),
            )
            await interaction.followup.send(embed=e, ephemeral=True)
            return

        # Fam-Blacklist check
        if self.db.fambl_check(ingame_id):
            entry = self.db.fambl_get_by_id(ingame_id)
            e = discord.Embed(
                title="🚫 Registrierung blockiert",
                description=(
                    f"{user.mention} steht auf der **Fam-Blacklist** und kann nicht registriert werden.\n"
                    f"**Grund:** {entry['reason']}"
                ),
                color=discord.Color.dark_red(),
            )
            await interaction.followup.send(embed=e, ephemeral=True)

            log_ch = self.bot.get_channel(config.LOG_CHANNEL)
            if log_ch:
                le = discord.Embed(title="⚠️ Blacklist – Registrierungsversuch", color=discord.Color.orange())
                le.add_field(name="Versucht von", value=interaction.user.mention)
                le.add_field(name="Für", value=user.mention)
                le.add_field(name="Ingame-Name", value=ingame_name)
                le.add_field(name="Ingame-ID", value=ingame_id)
                await log_ch.send(embed=le)
            return

        # Register
        ok = self.db.register_user(discord_id, ingame_name, ingame_id)
        if not ok:
            e = discord.Embed(
                title="❌ Fehler",
                description="Registrierung fehlgeschlagen. Wende dich an einen Admin.",
                color=discord.Color.red(),
            )
            await interaction.followup.send(embed=e, ephemeral=True)
            return

        # Rename user: Vorname Nachname | ID
        nickname = f"{vorname} {nachname} | {ingame_id}"
        try:
            await user.edit(nick=nickname, reason="EventBot3000 Registrierung")
        except discord.Forbidden:
            pass  # Bot hat keine Rechte den Nick zu ändern (z.B. Owner)

        # Assign Rekrut role
        await self._assign_rank_role(interaction.guild, user, 1)

        e = discord.Embed(
            title="✅ Registrierung erfolgreich",
            description=f"{user.mention} wurde erfolgreich registriert.",
            color=discord.Color.green(),
        )
        e.add_field(name="Ingame-Name", value=ingame_name, inline=True)
        e.add_field(name="Ingame-ID", value=ingame_id, inline=True)
        e.add_field(name="Rang", value=rank_label(1), inline=True)
        e.add_field(name="Nickname gesetzt", value=f"`{nickname}`", inline=False)
        await interaction.followup.send(embed=e, ephemeral=True)

        log_ch = self.bot.get_channel(config.LOG_CHANNEL)
        if log_ch:
            le = discord.Embed(title="[JOIN] Neuer User registriert", color=discord.Color.green())
            le.add_field(name="Registriert von", value=interaction.user.mention)
            le.add_field(name="Discord", value=user.mention)
            le.add_field(name="Ingame-Name", value=ingame_name)
            le.add_field(name="Ingame-ID", value=ingame_id)
            await log_ch.send(embed=le)

        self.db.log("REGISTER", str(interaction.user.id), discord_id,
                    f"Name={ingame_name} ID={ingame_id}")

    # ── /profil ────────────────────────────────────────────────────────────────

    @app_commands.command(name="profil", description="Zeigt dein Profil oder das eines anderen Users an")
    @app_commands.describe(user="Discord-User (leer = eigenes Profil)")
    async def profil(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        u = self.db.get_user(str(target.id))
        if not u:
            e = discord.Embed(
                title="❌ Nicht registriert",
                description=f"{target.mention} ist nicht registriert.",
                color=discord.Color.red(),
            )
            await interaction.response.send_message(embed=e, ephemeral=True)
            return

        on_ebl = self.db.eventbl_check(str(target.id))

        e = discord.Embed(title=f"👤 Profil – {u['ingame_name']}", color=discord.Color.blurple())
        e.set_thumbnail(url=target.display_avatar.url)
        e.add_field(name="Discord", value=target.mention, inline=True)
        e.add_field(name="Ingame-Name", value=u["ingame_name"], inline=True)
        e.add_field(name="Ingame-ID", value=u["ingame_id"], inline=True)
        e.add_field(name="Rang", value=rank_label(u["rank"]), inline=True)
        e.add_field(name="Gesamte Auszahlungen", value=f"${u['total_payout']:,}", inline=True)
        e.add_field(name="Event-Blacklist", value="🔴 Ja" if on_ebl else "🟢 Nein", inline=True)
        e.set_footer(text=f"Registriert am {u['joined_at'][:10]}")
        await interaction.response.send_message(embed=e)

    # ── Helper ─────────────────────────────────────────────────────────────────

    async def _assign_rank_role(self, guild: discord.Guild, member: discord.Member, rank: int):
        if not guild:
            return
        # Role names are stored as "N | Name" in DB after /rang-setup
        role_name = self.db.cfg_get_str(f"rank_role_{rank}")
        if not role_name:
            return
        role = discord.utils.get(guild.roles, name=role_name)
        if not role:
            return
        # Remove all rank roles (any role matching "N | ..." pattern)
        old_roles = [r for r in member.roles if _is_rank_role(r.name)]
        try:
            await member.remove_roles(*old_roles, reason="Rang-Update")
            await member.add_roles(role, reason="Rang-Update")
        except discord.Forbidden:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Registration(bot))
