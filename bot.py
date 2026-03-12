import discord
from discord.ext import commands
import asyncio
import config
from database import Database


intents = discord.Intents.all()


class EventBot3000(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.db = Database()

    def get_effective_rank(self, member: discord.Member) -> int:
        """Returns the highest rank from DB or from Discord roles set up via /rang-setup."""
        db_user = self.db.get_user(str(member.id))
        db_rank = db_user["rank"] if db_user else 0
        if member.guild:
            for rank_num in range(10, 0, -1):
                role_name = self.db.cfg_get_str(f"rank_role_{rank_num}")
                if role_name and discord.utils.get(member.roles, name=role_name):
                    return max(db_rank, rank_num)
        return db_rank

    def has_min_rank_or_admin(self, member: discord.Member, min_rank: int) -> bool:
        """Returns True if member has rank >= min_rank OR the configured admin role."""
        if self.get_effective_rank(member) >= min_rank:
            return True
        admin_role_id = self.db.cfg_get("admin_role_id")
        if admin_role_id and member.guild:
            role = member.guild.get_role(admin_role_id)
            if role and role in member.roles:
                return True
        return False

    async def setup_hook(self):
        # Load cogs
        for cog in ("cogs.registration", "cogs.events", "cogs.payouts",
                    "cogs.blacklist", "cogs.admin"):
            await self.load_extension(cog)
            print(f"  ✓ Loaded {cog}")

        # Sync slash commands to the guild (instant; no 1h delay)
        guild = discord.Object(id=config.GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print("  ✓ Slash commands synced to guild")

    async def on_ready(self):
        print(f"\nEventBot3000 online as {self.user}  (ID: {self.user.id})")

        # Re-register persistent views for all open events
        from cogs.events import EventView
        open_events = self.db.get_open_events()
        for event in open_events:
            self.add_view(EventView(event["id"]))
        print(f"  ✓ Re-registered {len(open_events)} persistent event view(s)")

        # Post / refresh the ranking message
        payouts_cog = self.get_cog("Payouts")
        if payouts_cog:
            await payouts_cog._update_ranking()

        await self.change_presence(
            activity=discord.Game(name="EventBot3000 | /register")
        )

    async def on_member_join(self, member: discord.Member):
        log_ch = self.get_channel(config.LOG_CHANNEL)
        if log_ch:
            e = discord.Embed(
                title="[JOIN] Member beigetreten",
                description=f"{member.mention} ist dem Server beigetreten.",
                color=discord.Color.green(),
            )
            e.set_thumbnail(url=member.display_avatar.url)
            e.set_footer(text=f"ID: {member.id}")
            await log_ch.send(embed=e)

    async def on_member_remove(self, member: discord.Member):
        log_ch = self.get_channel(config.LOG_CHANNEL)
        if log_ch:
            e = discord.Embed(
                title="[LEAVE] Member verlassen",
                description=f"**{member.display_name}** hat den Server verlassen.",
                color=discord.Color.red(),
            )
            e.set_footer(text=f"ID: {member.id}")
            await log_ch.send(embed=e)

    async def on_member_update(self, before: discord.Member, after: discord.Member):
        # Log role changes
        added   = [r for r in after.roles  if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if not added and not removed:
            return

        log_ch = self.get_channel(config.LOG_CHANNEL)
        if not log_ch:
            return

        e = discord.Embed(title="[ROLE] Rollen-Änderung", color=discord.Color.blurple())
        e.add_field(name="User", value=after.mention)
        if added:
            e.add_field(name="Hinzugefügt", value=", ".join(r.name for r in added))
        if removed:
            e.add_field(name="Entfernt", value=", ".join(r.name for r in removed))
        await log_ch.send(embed=e)


if __name__ == "__main__":
    bot = EventBot3000()
    bot.run(config.BOT_TOKEN)
