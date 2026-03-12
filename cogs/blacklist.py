import discord
from discord import app_commands
from discord.ext import commands
import config

ITEMS_PER_PAGE = 10


def _is_management(rank: int) -> bool:
    return rank >= config.MANAGEMENT_MIN_RANK


class Blacklist(commands.Cog):
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

    async def _log(self, action: str, actor: discord.Member, details: str):
        ch = self.bot.get_channel(config.LOG_CHANNEL)
        if ch:
            e = discord.Embed(title=f"[BL] {action}", color=discord.Color.red())
            e.add_field(name="Von", value=actor.mention)
            e.add_field(name="Details", value=details, inline=False)
            await ch.send(embed=e)

    # ══════════════════════════════════════════════
    #  FAM BLACKLIST
    # ══════════════════════════════════════════════

    @app_commands.command(name="fambl-add", description="Füge jemanden zur Fam-Blacklist hinzu")
    @app_commands.describe(
        ingame_name="Ingame-Name",
        ingame_id="Ingame-ID",
        reason="Grund",
    )
    async def fambl_add(self, interaction: discord.Interaction,
                        ingame_name: str, ingame_id: str, reason: str):
        if not await self._check_mgmt(interaction):
            return

        ok = self.db.fambl_add(ingame_name, ingame_id, reason, str(interaction.user.id))
        if not ok:
            await interaction.response.send_message(
                f"⚠️ Ingame-ID `{ingame_id}` ist bereits auf der Fam-Blacklist.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ **{ingame_name}** (ID: `{ingame_id}`) wurde zur **Fam-Blacklist** hinzugefügt.",
            ephemeral=True,
        )
        await self._log(
            "Fam-Blacklist: Hinzugefügt",
            interaction.user,
            f"Name: {ingame_name} | ID: {ingame_id} | Grund: {reason}",
        )
        self.db.log("FAMBL_ADD", str(interaction.user.id), ingame_id,
                    f"name={ingame_name} reason={reason}")

    @app_commands.command(name="fambl-remove", description="Entferne jemanden von der Fam-Blacklist")
    @app_commands.describe(ingame_id="Ingame-ID des Eintrags")
    async def fambl_remove(self, interaction: discord.Interaction, ingame_id: str):
        if not await self._check_mgmt(interaction):
            return

        ok = self.db.fambl_remove(ingame_id)
        if not ok:
            await interaction.response.send_message(
                f"❌ Ingame-ID `{ingame_id}` wurde nicht auf der Fam-Blacklist gefunden.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ ID `{ingame_id}` wurde von der **Fam-Blacklist** entfernt.", ephemeral=True
        )
        await self._log("Fam-Blacklist: Entfernt", interaction.user, f"ID: {ingame_id}")
        self.db.log("FAMBL_REMOVE", str(interaction.user.id), ingame_id)

    @app_commands.command(name="fambl-check", description="Prüfe ob eine Ingame-ID auf der Fam-Blacklist ist")
    @app_commands.describe(ingame_id="Ingame-ID")
    async def fambl_check(self, interaction: discord.Interaction, ingame_id: str):
        entry = self.db.fambl_get_by_id(ingame_id)
        if entry:
            e = discord.Embed(
                title="🚫 Auf der Fam-Blacklist",
                color=discord.Color.dark_red(),
            )
            e.add_field(name="Ingame-Name", value=entry["ingame_name"])
            e.add_field(name="Ingame-ID", value=entry["ingame_id"])
            e.add_field(name="Grund", value=entry["reason"], inline=False)
            e.add_field(name="Hinzugefügt am", value=entry["added_at"][:10])
        else:
            e = discord.Embed(
                title="✅ Nicht auf der Fam-Blacklist",
                description=f"ID `{ingame_id}` ist **nicht** gelistet.",
                color=discord.Color.green(),
            )
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="fambl-list", description="Zeige die Fam-Blacklist")
    @app_commands.describe(seite="Seite (Standard: 1)")
    async def fambl_list(self, interaction: discord.Interaction, seite: int = 1):
        if not await self._check_mgmt(interaction):
            return

        entries = self.db.fambl_get_all()
        if not entries:
            await interaction.response.send_message(
                "📭 Die Fam-Blacklist ist leer.", ephemeral=True
            )
            return

        pages = max(1, (len(entries) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        seite = max(1, min(seite, pages))
        start = (seite - 1) * ITEMS_PER_PAGE
        slice_ = entries[start: start + ITEMS_PER_PAGE]

        e = discord.Embed(title="🚫 Fam-Blacklist", color=discord.Color.dark_red())
        for entry in slice_:
            e.add_field(
                name=f"{entry['ingame_name']} (ID: {entry['ingame_id']})",
                value=f"Grund: {entry['reason']}\nAm: {entry['added_at'][:10]}",
                inline=False,
            )
        e.set_footer(text=f"Seite {seite}/{pages} • {len(entries)} Einträge gesamt")
        await interaction.response.send_message(embed=e, ephemeral=True)

    # ══════════════════════════════════════════════
    #  EVENT BLACKLIST
    # ══════════════════════════════════════════════

    @app_commands.command(name="eventbl-add", description="Füge einen User zur Event-Blacklist hinzu")
    @app_commands.describe(user="Discord-User", reason="Grund")
    async def eventbl_add(self, interaction: discord.Interaction, user: discord.Member, reason: str):
        if not await self._check_mgmt(interaction):
            return

        target = self.db.get_user(str(user.id))
        ingame_name = target["ingame_name"] if target else user.display_name

        ok = self.db.eventbl_add(str(user.id), ingame_name, reason, str(interaction.user.id))
        if not ok:
            await interaction.response.send_message(
                f"⚠️ {user.mention} ist bereits auf der Event-Blacklist.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ **{ingame_name}** wurde zur **Event-Blacklist** hinzugefügt.", ephemeral=True
        )
        await self._log(
            "Event-Blacklist: Hinzugefügt",
            interaction.user,
            f"User: {user.mention} ({ingame_name}) | Grund: {reason}",
        )
        self.db.log("EVENTBL_ADD", str(interaction.user.id), str(user.id),
                    f"name={ingame_name} reason={reason}")

    @app_commands.command(name="eventbl-remove", description="Entferne einen User von der Event-Blacklist")
    @app_commands.describe(user="Discord-User")
    async def eventbl_remove(self, interaction: discord.Interaction, user: discord.Member):
        if not await self._check_mgmt(interaction):
            return

        ok = self.db.eventbl_remove(str(user.id))
        if not ok:
            await interaction.response.send_message(
                f"❌ {user.mention} ist nicht auf der Event-Blacklist.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ {user.mention} wurde von der **Event-Blacklist** entfernt.", ephemeral=True
        )
        await self._log("Event-Blacklist: Entfernt", interaction.user, f"User: {user.mention}")
        self.db.log("EVENTBL_REMOVE", str(interaction.user.id), str(user.id))

    @app_commands.command(name="eventbl-check", description="Prüfe ob ein User auf der Event-Blacklist ist")
    @app_commands.describe(user="Discord-User")
    async def eventbl_check(self, interaction: discord.Interaction, user: discord.Member):
        entry = self.db.eventbl_get(str(user.id))
        if entry:
            e = discord.Embed(
                title="🚫 Auf der Event-Blacklist",
                color=discord.Color.dark_red(),
            )
            e.add_field(name="Discord", value=user.mention)
            e.add_field(name="Ingame-Name", value=entry["ingame_name"])
            e.add_field(name="Grund", value=entry["reason"], inline=False)
            e.add_field(name="Hinzugefügt am", value=entry["added_at"][:10])
        else:
            e = discord.Embed(
                title="✅ Nicht auf der Event-Blacklist",
                description=f"{user.mention} ist **nicht** gelistet.",
                color=discord.Color.green(),
            )
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="eventbl-list", description="Zeige die Event-Blacklist")
    @app_commands.describe(seite="Seite (Standard: 1)")
    async def eventbl_list(self, interaction: discord.Interaction, seite: int = 1):
        if not await self._check_mgmt(interaction):
            return

        entries = self.db.eventbl_get_all()
        if not entries:
            await interaction.response.send_message(
                "📭 Die Event-Blacklist ist leer.", ephemeral=True
            )
            return

        pages = max(1, (len(entries) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
        seite = max(1, min(seite, pages))
        start = (seite - 1) * ITEMS_PER_PAGE
        slice_ = entries[start: start + ITEMS_PER_PAGE]

        e = discord.Embed(title="🚫 Event-Blacklist", color=discord.Color.dark_red())
        for entry in slice_:
            e.add_field(
                name=f"{entry['ingame_name']}",
                value=f"Grund: {entry['reason']}\nAm: {entry['added_at'][:10]}",
                inline=False,
            )
        e.set_footer(text=f"Seite {seite}/{pages} • {len(entries)} Einträge gesamt")
        await interaction.response.send_message(embed=e, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Blacklist(bot))
