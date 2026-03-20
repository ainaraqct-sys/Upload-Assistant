# Upload Assistant © 2025 Audionut & wastaken7 — Licensed under UAPL v1.0
# ruff: noqa: E402
import asyncio
import datetime
import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Optional, Union

warnings.filterwarnings("ignore", category=DeprecationWarning, module="discord.player")

import aiohttp
import discord
from discord.ext import commands

from src.console import console


async def run(config: Mapping[str, Any]) -> None:
    """
    Starts the bot. If you want to create a database connection pool or other session for the bot to use,
    create it here and pass it to the bot as a kwarg.
    """
    intents = discord.Intents.default()
    intents.message_content = True

    bot = Bot(config=config, description=config["DISCORD"]["discord_bot_description"], intents=intents)

    try:
        await bot.start(config["DISCORD"]["discord_bot_token"])
    except KeyboardInterrupt:
        await bot.close()


class Bot(commands.Bot):
    def __init__(self, *, config: Mapping[str, Any], description: str, intents: discord.Intents) -> None:
        super().__init__(command_prefix=self.get_prefix_, description=description, intents=intents)
        self.start_time: Optional[datetime.datetime] = None
        self.app_info: Optional[discord.AppInfo] = None
        self.config: Mapping[str, Any] = config

    async def setup_hook(self) -> None:
        # Called before the bot connects to Discord
        asyncio.create_task(self.track_start())
        await self.load_all_extensions()

    async def track_start(self) -> None:
        """
        Waits for the bot to connect to discord and then records the time.
        Can be used to work out uptime.
        """
        await self.wait_until_ready()
        self.start_time = datetime.datetime.now(datetime.timezone.utc)

    async def get_prefix_(self, bot: commands.Bot, message: discord.Message) -> Sequence[str]:
        """
        A coroutine that returns a prefix.
        """
        prefix = [self.config["DISCORD"]["command_prefix"]]
        return commands.when_mentioned_or(*prefix)(bot, message)

    async def load_all_extensions(self) -> None:
        """
        Attempts to load all .py files in /cogs/ as cog extensions
        """
        await self.wait_until_ready()
        await asyncio.sleep(1)  # ensure that on_ready has completed and finished printing
        # cogs/redaction.py is a helper module (not an extension).
        # cogs/commands.py has been removed.
        excluded = {"redaction", "commands"}

        cogs = [x.stem for x in Path("cogs").glob("*.py") if x.stem not in excluded]
        for extension in cogs:
            try:
                await self.load_extension(f"cogs.{extension}")
                console.print(f"loaded {extension}", markup=False)
            except Exception as e:
                error = f"{extension}\n {type(e).__name__} : {e}"
                console.print(f"failed to load extension {error}", markup=False)
            console.print("-" * 10, markup=False)

    async def on_ready(self) -> None:
        """
        This event is called every time the bot connects or resumes connection.
        """
        console.print("-" * 10, markup=False)
        self.app_info = await self.application_info()
        user = self.user
        if user is None:
            console.print("[red]Discord client user unavailable[/red]")
            return
        console.print(f"Logged in as: {user.name}\nUsing discord.py version: {discord.__version__}\nOwner: {self.app_info.owner}\n", markup=False)
        console.print("-" * 10, markup=False)
        channel = self.get_channel(int(self.config["DISCORD"]["discord_channel_id"]))
        if channel and isinstance(channel, discord.abc.Messageable):
            await channel.send(f"{user.name} is now online")

    async def on_message(self, message: discord.Message) -> None:
        """
        This event triggers on every message received by the bot. Including one's that it sent itself.
        """
        if message.author.bot:
            return  # ignore all bots
        await self.process_commands(message)


BotLike = Union[discord.Client, commands.Bot]


_COLOR_GREEN = 3066993   # #2ecc71
_COLOR_RED = 15158332    # #e74c3c
_COLOR_ORANGE = 15105570 # #e67e22
_COLOR_BLUE = 3447003    # #3498db


class DiscordNotifier:
    @staticmethod
    async def _post_webhook(webhook_url: str, payload: dict[str, Any]) -> bool:
        """POST a raw payload dict to a Discord webhook URL."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=payload) as resp:
                    if resp.status in (200, 204):
                        return True
                    console.print(f"[yellow]Discord webhook returned HTTP {resp.status}")
                    return False
        except Exception as e:
            console.print(f"[yellow]Discord webhook error: {e}")
            return False

    @staticmethod
    async def _send_via_webhook(webhook_url: str, message: str) -> bool:
        """Send a plain text message to a Discord webhook URL."""
        return await DiscordNotifier._post_webhook(webhook_url, {"content": message})

    @staticmethod
    async def _send_embeds_via_webhook(webhook_url: str, embeds: list[dict[str, Any]]) -> bool:
        """Send one or more embeds to a Discord webhook URL."""
        return await DiscordNotifier._post_webhook(webhook_url, {"embeds": embeds})

    @staticmethod
    def _check_unattended(config: Mapping[str, Any], meta: Optional[Mapping[str, Any]]) -> bool:
        """Return False if only_unattended is set and the current run is not unattended."""
        only_unattended = config.get("DISCORD", {}).get("only_unattended", False)
        unattended = bool(meta and meta.get("unattended", False))
        return not (only_unattended and not unattended)

    @staticmethod
    def _simple_embed(description: str, color: int = _COLOR_BLUE) -> dict[str, Any]:
        """Build a minimal embed with just a description."""
        return {"description": description, "color": color}

    @staticmethod
    def _build_upload_embeds(meta: Mapping[str, Any], tracker_status: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Build one embed per tracker result (success or meaningful failure)."""
        default_release_name = str(meta.get("name", meta.get("title", "Unknown Release")))
        embeds: list[dict[str, Any]] = []

        for tracker, status in tracker_status.items():
            if not isinstance(status, dict):
                continue

            uploaded = status.get("upload", False)
            torrent_id = status.get("torrent_id", "")
            release_name = str(status.get("release_name", "") or default_release_name)

            if uploaded:
                fields: list[dict[str, Any]] = []
                if torrent_id:
                    fields.append({"name": "ID", "value": str(torrent_id), "inline": True})
                torrent_url = status.get("torrent_url", "")
                torrent_value = f"[{release_name}]({torrent_url})" if torrent_url else release_name
                fields.append({"name": "Torrent", "value": torrent_value, "inline": False})
                embeds.append({
                    "title": f"Nouvel upload {tracker}",
                    "color": _COLOR_GREEN,
                    "fields": fields,
                })
            else:
                if status.get("dupe", False):
                    reason = "dupe"
                    color = _COLOR_ORANGE
                elif status.get("banned", False):
                    reason = "banni"
                    color = _COLOR_RED
                elif status.get("skipped", False):
                    reason = status.get("skip_reason", "ignoré")
                    color = _COLOR_ORANGE
                else:
                    # Generic upload error — include status_message if available
                    status_msg = status.get("status_message", "")
                    if isinstance(status_msg, dict):
                        detail = status_msg.get("detail", "")
                        detail_str = str(detail).lower()
                        if "dupliqué" in detail_str or "already exists" in detail_str or "duplicate" in detail_str or status_msg.get("error", "").startswith("HTTP 409"):
                            reason = "dupe"
                            color = _COLOR_ORANGE
                        else:
                            reason = status_msg.get("message") or status_msg.get("error") or "erreur"
                            color = _COLOR_RED
                    elif status_msg:
                        reason = str(status_msg)[:200]
                        color = _COLOR_RED
                    else:
                        reason = "erreur"
                        color = _COLOR_RED

                embeds.append({
                    "title": f"Echec {tracker}",
                    "color": color,
                    "fields": [
                        {"name": "Raison", "value": reason, "inline": False},
                        {"name": "Torrent", "value": release_name, "inline": False},
                    ],
                })

        return embeds

    @staticmethod
    async def send_discord_notification(
        config: Mapping[str, Any],
        bot: Optional[BotLike],
        message: str,
        debug: bool = False,
        meta: Optional[Mapping[str, Any]] = None,
        webhook_url: Optional[str] = None,
    ) -> bool:
        """
        Send a notification message to Discord via webhook (preferred) or bot.

        Args:
            bot: Discord bot instance (can be None when using webhook)
            message: Message string to send
            meta: Optional meta dict for debug logging
            webhook_url: Discord webhook URL (takes priority over bot)

        Returns:
            bool: True if message was sent successfully, False otherwise
        """
        if not DiscordNotifier._check_unattended(config, meta):
            return False

        # Webhook path — send as a simple embed
        if webhook_url:
            result = await DiscordNotifier._send_embeds_via_webhook(
                webhook_url, [DiscordNotifier._simple_embed(message)]
            )
            if debug and result:
                console.print(f"[green]Discord webhook notification sent: {message}")
            return result

        # Legacy bot path
        if not bot or not hasattr(bot, "is_ready") or not bot.is_ready():
            if debug:
                console.print("[yellow]Discord bot not ready - skipping notifications")
            return False

        try:
            channel_id = int(config["DISCORD"]["discord_channel_id"])
            channel = bot.get_channel(channel_id)
            if channel and isinstance(channel, discord.abc.Messageable):
                await channel.send(message)
                if debug:
                    console.print(f"[green]Discord notification sent: {message}")
                return True
            else:
                console.print("[yellow]Discord channel not found")
                return False
        except Exception as e:
            console.print(f"[yellow]Discord notification error: {e}")
            return False

    @staticmethod
    async def send_upload_status_notification(
        config: Mapping[str, Any],
        bot: Optional[BotLike],
        meta: Mapping[str, Any],
        webhook_url: Optional[str] = None,
    ) -> bool:
        """Send Discord notification with upload status including failed trackers."""
        if not DiscordNotifier._check_unattended(config, meta):
            return False

        tracker_status = meta.get("tracker_status", {})
        if not tracker_status:
            return False

        # Webhook path — send rich embeds
        if webhook_url:
            embeds = DiscordNotifier._build_upload_embeds(meta, tracker_status)
            if not embeds:
                return False
            return await DiscordNotifier._send_embeds_via_webhook(webhook_url, embeds)

        # Legacy bot path — plain text fallback
        successful_uploads: list[str] = [t for t, s in tracker_status.items() if s.get("upload", False)]
        failed_trackers: list[str] = []
        for tracker, status in tracker_status.items():
            if not status.get("upload", False):
                if status.get("banned", False):
                    failed_trackers.append(f"{tracker} (banned)")
                elif status.get("skipped", False):
                    failed_trackers.append(f"{tracker} (skipped)")
                elif status.get("dupe", False):
                    failed_trackers.append(f"{tracker} (dupe)")

        release_name = meta.get("name", meta.get("title", "Unknown Release"))
        message_parts: list[str] = []
        if successful_uploads:
            message_parts.append(f"✅ **Uploaded to:** {', '.join(successful_uploads)} - {release_name}")
        if failed_trackers:
            message_parts.append(f"❌ **Failed:** {', '.join(failed_trackers)}")
        if not message_parts:
            return False

        if not bot or not hasattr(bot, "is_ready") or not bot.is_ready():
            return False

        try:
            channel_id = int(config["DISCORD"]["discord_channel_id"])
            channel = bot.get_channel(channel_id)
            if channel and isinstance(channel, discord.abc.Messageable):
                await channel.send("\n".join(message_parts))
                return True
        except Exception as e:
            console.print(f"[yellow]Discord notification error: {e}")

        return False


async def send_discord_notification(
    config: Mapping[str, Any],
    bot: Optional[BotLike],
    message: str,
    debug: bool = False,
    meta: Optional[Mapping[str, Any]] = None,
    webhook_url: Optional[str] = None,
) -> bool:
    return await DiscordNotifier.send_discord_notification(config, bot, message, debug=debug, meta=meta, webhook_url=webhook_url)


async def send_upload_status_notification(
    config: Mapping[str, Any],
    bot: Optional[BotLike],
    meta: Mapping[str, Any],
    webhook_url: Optional[str] = None,
) -> bool:
    return await DiscordNotifier.send_upload_status_notification(config, bot, meta, webhook_url=webhook_url)
