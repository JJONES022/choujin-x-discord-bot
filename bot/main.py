import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

from bot.database import Store
from bot.manga_monitor import latest_chapter
from bot.english_monitor import latest_english
from bot.release_schedule import schedule_text

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
DB_PATH = os.getenv("DATABASE_PATH", "data/bot.db")
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
store = Store(DB_PATH)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("choujin_x_bot")

ROLE_NAMES = {"manga": "Manga Updates", "anime": "Anime Updates"}


async def countdown_text():
    last_jp = await store.last_jp_release()
    last_en = await store.last_en_release()
    verified = await store.get_state("last_en_hour_verified") == "1"
    return schedule_text(last_jp, last_en, english_hour_verified=verified)


async def ensure_role(guild: discord.Guild, category: str) -> discord.Role:
    name = ROLE_NAMES[category]
    existing = discord.utils.get(guild.roles, name=name)
    if existing:
        return existing
    return await guild.create_role(
        name=name, mentionable=False, reason="Choujin X notification opt-in role"
    )


class SubscriptionView(discord.ui.View):
    """Persistent personal DM subscription controls."""
    def __init__(self, scope="dm", manga=False, anime=False):
        super().__init__(timeout=None)
        self.manga_button.label = f"Manga: {'ON' if manga else 'OFF'}"
        self.anime_button.label = f"Anime: {'ON' if anime else 'OFF'}"

    async def toggle(self, interaction: discord.Interaction, category: str):
        if interaction.guild is not None:
            await interaction.response.send_message("These buttons are for personal DMs only. Use /subscribe.", ephemeral=True)
            return
        prefs = await store.get_dm(interaction.user.id) or {"manga": 0, "anime": 0}
        manga, anime = bool(prefs["manga"]), bool(prefs["anime"])
        if category == "manga":
            manga = not manga
        else:
            anime = not anime
        await store.set_dm(interaction.user.id, manga, anime)
        await interaction.response.edit_message(
            content="**Choujin X — Personal DM Notifications**\nChoose either category or both. Click again to unsubscribe.",
            view=SubscriptionView(manga=manga, anime=anime))

    @discord.ui.button(label="Manga: OFF", style=discord.ButtonStyle.success, custom_id="cx:dm:manga")
    async def manga_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.toggle(interaction, "manga")

    @discord.ui.button(label="Anime: OFF", style=discord.ButtonStyle.danger, custom_id="cx:dm:anime")
    async def anime_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.toggle(interaction, "anime")


def is_admin(member):
    return isinstance(member, discord.Member) and (member.guild.owner_id == member.id or member.guild_permissions.administrator)


class AnnouncementChannelView(discord.ui.View):
    """Single-use confirmation, tied to the initiating administrator and channel."""
    def __init__(self, owner_id: int, guild_id: int, channel_id: int):
        super().__init__(timeout=180)
        self.owner_id, self.guild_id, self.channel_id = owner_id, guild_id, channel_id

    async def interaction_check(self, interaction: discord.Interaction):
        if (interaction.user.id != self.owner_id or not is_admin(interaction.user)
                or not interaction.guild or interaction.guild.id != self.guild_id):
            await interaction.response.send_message("Only the administrator who requested this change can confirm it.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Yes, Use This Channel", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = await store.get_server(self.guild_id)
        if current and current['channel_id'] == self.channel_id:
            await interaction.response.edit_message(content="This channel is already configured for public announcements.", view=None)
            self.stop()
            return
        # A single announcement channel per guild; both categories enabled.
        await store.set_server(self.guild_id, self.channel_id, True, True)
        await interaction.response.edit_message(
            content=f"Public Manga and Anime announcements will now be posted in <#{self.channel_id}>. "
                    "Only subscribed roles will be pinged; DM subscriptions are unchanged.", view=None)
        self.stop()

    @discord.ui.button(label="No, Keep Current", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="No changes made to the announcement channel.", view=None)
        self.stop()


class MemberRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def toggle_role(self, interaction: discord.Interaction, category: str):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Role buttons only work in servers.", ephemeral=True)
            return
        role = discord.utils.get(guild.roles, name=ROLE_NAMES[category])
        if role is None:
            await interaction.response.send_message(
                "The notification role is missing. Ask an administrator to reconfigure notifications.", ephemeral=True
            )
            return
        member = interaction.user
        if not isinstance(member, discord.Member):
            member = await guild.fetch_member(interaction.user.id)
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Member opted out of Choujin X notifications")
                status = "removed"
            else:
                await member.add_roles(role, reason="Member opted in to Choujin X notifications")
                status = "added"
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message(
                "I couldn't change your role. An administrator should check my Manage Roles permission and role position.",
                ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"{ROLE_NAMES[category]} role {status}.", ephemeral=True
        )

    @discord.ui.button(label="Manga Updates", style=discord.ButtonStyle.success, custom_id="cx:role:manga")
    async def manga_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.toggle_role(interaction, "manga")

    @discord.ui.button(label="Anime Updates", style=discord.ButtonStyle.danger, custom_id="cx:role:anime")
    async def anime_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.toggle_role(interaction, "anime")


def role_panel_text():
    return (
        "**Choujin X Notification Roles**\n"
        "Click a button to **add or remove** that notification role. You can have both roles.\n"
        "*These buttons manage server roles, not personal DM subscriptions.*"
    )


async def ensure_role_panel(guild, channel):
    key = f"role_panel:{guild.id}"
    saved = await store.get_state(key)
    if saved:
        try:
            channel_id, message_id = map(int, saved.split(':'))
            if channel_id == channel.id:
                message = await channel.fetch_message(message_id)
                await message.edit(content=role_panel_text(), view=MemberRoleView())
                return
        except (ValueError, discord.NotFound, discord.Forbidden):
            pass
    message = await channel.send(role_panel_text(), view=MemberRoleView())
    await store.set_state(key, f"{channel.id}:{message.id}")


intents = discord.Intents.default()
intents.message_content = True


class ChoujinBot(commands.Bot):
    async def setup_hook(self):
        await store.init()
        self.add_view(SubscriptionView("dm"))
        self.add_view(MemberRoleView())
        synced = await self.tree.sync()
        logger.info("Synced slash commands: %s", [command.name for command in synced])
        logger.info("Persistent subscription and role views registered.")


bot = ChoujinBot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    if not manga_monitor_loop.is_running():
        manga_monitor_loop.start()
    if not english_monitor_loop.is_running():
        english_monitor_loop.start()
    logger.info("Logged in as %s", bot.user)


@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.guild and bot.user and bot.user in message.mentions:
        if is_admin(message.author):
            config = await store.get_server(message.guild.id)
            if config and config['channel_id'] == message.channel.id:
                await message.reply("This is already the configured public announcement channel.", mention_author=False)
            else:
                existing = f"<#{config['channel_id']}>" if config else "none"
                question = (
                    f"**Change Announcement Channel?**\nCurrent channel: {existing}\n"
                    f"Would you like all future public Manga and Anime announcements to be sent to {message.channel.mention}?"
                    if config else
                    f"**Configure Announcement Channel**\nWould you like to send future public Manga and Anime announcements to {message.channel.mention}?"
                )
                await message.reply(question, view=AnnouncementChannelView(
                    message.author.id, message.guild.id, message.channel.id), mention_author=False)
        # Non-admin mentions cannot configure or redirect announcements.
    await bot.process_commands(message)


@bot.tree.command(name="subscribe", description="Configure your personal Choujin X DM subscriptions")
async def subscribe(interaction: discord.Interaction):
    prefs = await store.get_dm(interaction.user.id) or {"manga": 0, "anime": 0}
    try:
        await interaction.user.send(
            "**Choujin X — Personal DM Notifications**\nChoose either category or both. Click again to unsubscribe.",
            view=SubscriptionView("dm", bool(prefs["manga"]), bool(prefs["anime"]))
        )
        await interaction.response.send_message("I sent you a DM with subscription buttons.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message(
            "I cannot DM you. Check your privacy settings or DM me first.", ephemeral=True
        )


@bot.tree.command(name="chapter", description="Show the current estimated chapter countdown")
async def chapter(interaction: discord.Interaction):
    await interaction.response.send_message(await countdown_text(), ephemeral=interaction.guild is not None)


@bot.tree.command(name="roles", description="Post the public Manga/Anime role subscription panel here (admins only)")
@app_commands.default_permissions(administrator=True)
async def roles(interaction: discord.Interaction):
    if not interaction.guild or not is_admin(interaction.user):
        await interaction.response.send_message("Only the server owner or an administrator can post role panels.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        for category in ("manga", "anime"):
            await ensure_role(interaction.guild, category)
        await ensure_role_panel(interaction.guild, interaction.channel)
    except (discord.Forbidden, discord.HTTPException) as exc:
        await interaction.followup.send(
            f"Couldn't post the role panel. Check Manage Roles, Send Messages and the bot's role hierarchy. ({exc})",
            ephemeral=True)
        return
    await interaction.followup.send(f"Role subscription buttons are ready in {interaction.channel.mention}.", ephemeral=True)


@tasks.loop(minutes=15)
async def manga_monitor_loop():
    """Track Japanese episode URL changes silently; don't fabricate dates."""
    try:
        latest = await latest_chapter()
        previous = await store.get_state('jp_episode_url')
        if previous != latest['url']:
            await store.set_state('jp_episode_url', latest['url'])
            logger.info('Japanese episode link %s: %s', 'baseline' if previous is None else 'changed', latest['url'])
            if previous is not None:
                logger.warning('Japanese episode changed. Publication date is not yet verified; schedule date not advanced.')
    except Exception as exc:
        logger.warning('Japanese publisher check failed: %s', exc)

@manga_monitor_loop.before_loop
async def before_manga_monitor():
    await bot.wait_until_ready()


async def deliver_update(category: str, finding_id: str, content: str):
    """Public guild announcement with category-specific role ping; plain opt-in DMs.

    Only enabled guild categories and DM subscribers receive messages. The delivery
    ledger prevents repeat sends when a monitor polls again or the bot restarts.
    """
    if category not in ROLE_NAMES:
        raise ValueError(f"Unknown notification category: {category}")

    for config in await store.servers():
        if not config[category]:
            continue
        destination = f"guild:{config['guild_id']}"
        if await store.is_delivered(finding_id, destination):
            continue
        guild = bot.get_guild(config['guild_id'])
        channel = guild.get_channel(config['channel_id']) if guild else None
        if channel is None:
            continue
        role = discord.utils.get(guild.roles, name=ROLE_NAMES[category])
        if role is None:
            logger.warning('No %s role in guild %s; announcement will be public without ping',
                           ROLE_NAMES[category], config['guild_id'])
        try:
            # Public message: never ephemeral. Restrict mentions to the selected role.
            # To actually notify a non-mentionable role, Discord requires the bot to
            # have Mention Everyone permission in this channel.
            await channel.send(
                (f'{role.mention}\n' if role else '') + content,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, users=False, roles=[role] if role else [],
                    replied_user=False),
            )
            await store.mark_delivered(finding_id, destination)
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning('%s announcement failed in guild %s: %s',
                           category, config['guild_id'], exc)

    dm_users = await (store.manga_dm_users() if category == 'manga'
                      else store.anime_dm_users())
    for user_id in dm_users:
        destination = f'dm:{user_id}'
        if await store.is_delivered(finding_id, destination):
            continue
        try:
            user = await bot.fetch_user(user_id)
            await user.send(content, allowed_mentions=discord.AllowedMentions.none())
            await store.mark_delivered(finding_id, destination)
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning('%s DM failed for user %s: %s', category, user_id, exc)


async def announce_schedule(finding_id, chapter):
    content = (f'**Choujin X Chapter {chapter} is now listed on VIZ!**\n'
               f'https://www.viz.com/shonenjump/chapters/choujin-x\n'
               f'https://mangaplus.shueisha.co.jp/titles/100160\n\n'
               + await countdown_text())
    await deliver_update('manga', finding_id, content)


@tasks.loop(minutes=15)
async def english_monitor_loop():
    try:
        latest = await latest_english()
        chapter = latest['chapter']
        previous = await store.get_state('last_en_chapter')
        if previous is None:
            # On first boot, initialize without announcing historical releases.
            known_2026_release = (chapter == '79.1' and latest['date'] == '2026-11-10')
            await store.set_last_en_release(latest['estimated_clock'], chapter, hour_verified=known_2026_release)
            await store.set_state('english_initial_chapter', chapter)
            logger.info('VIZ English baseline saved: Chapter %s (%s)', chapter, latest['date'])
            return
        if previous != chapter:
            # Never announce an older chapter if publisher ordering changes.
            def chapter_parts(c):
                return tuple(int(x) for x in c.split('.'))
            if chapter_parts(chapter) < chapter_parts(previous):
                logger.warning('VIZ listing moved backwards (%s -> %s); ignoring', previous, chapter)
                return
            await store.set_last_en_release(latest['estimated_clock'], chapter)
            logger.info('New English chapter verified on VIZ: %s', chapter)
        finding_id = 'english:viz:' + chapter
        # If the process crashed mid-delivery, retry pending destinations.
        # Baseline chapter must never be sent.
        baseline = await store.get_state('english_initial_chapter')
        if baseline is None:
            await store.set_state('english_initial_chapter', chapter)
            return
        if chapter != baseline:
            await announce_schedule(finding_id, chapter)
    except Exception as exc:
        logger.warning('English VIZ check failed (no alert sent): %s', exc)

@english_monitor_loop.before_loop
async def before_english_monitor():
    await bot.wait_until_ready()


async def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing from .env")
    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
