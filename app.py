from flask import Flask, render_template, request, jsonify, session, redirect
from werkzeug.security import generate_password_hash, check_password_hash
import discord
from discord.ext import commands
import json, os, sys, threading, asyncio, logging, secrets, ssl, urllib.request, urllib.parse, base64
import certifi
import aiohttp
from datetime import datetime, timedelta

logging.getLogger("werkzeug").setLevel(logging.ERROR)

# In-memory pending tokens
PENDING_VERIFICATIONS = {}
# user_id → guild_id, waiting for a DM reply with their Fortnite name
PENDING_NICKNAME = {}
# channel_id → {guild_id, s}, waiting for dispatch code reply
PENDING_DISPATCH = {}

EPIC_AUTH_URL    = "https://www.epicgames.com/id/authorize"
EPIC_TOKEN_URL   = "https://api.epicgames.dev/epic/oauth/v2/token"
EPIC_USERINFO_URL = "https://api.epicgames.dev/epic/oauth/v2/userInfo"

# Railway / cloud sets PORT and DISCORD_TOKEN as environment variables
PORT = int(os.environ.get("PORT", 3000))
ENV_TOKEN = os.environ.get("DISCORD_TOKEN", "")

flask_app = Flask(__name__)
flask_app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))
flask_app.config["TEMPLATES_AUTO_RELOAD"] = True

LOGIN_USERNAME = os.environ.get("LOGIN_USERNAME", "")
LOGIN_PASSWORD = os.environ.get("LOGIN_PASSWORD", "")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
BANNER_PATH = os.path.join(BASE_DIR, "static", "ocean_banner.png")

SCRIMS = {
    "solos":         {"name": "Solo",           "emoji": "🔫", "color": 0x00B4D8, "hex": "#00B4D8", "party": 1},
    "duos":          {"name": "Duos",           "emoji": "👥", "color": 0x06D6A0, "hex": "#06D6A0", "party": 2},
    "trios":         {"name": "Trios",          "emoji": "🔱", "color": 0x9B59B6, "hex": "#9B59B6", "party": 3},
    "squads":        {"name": "Squads",         "emoji": "⚔️",  "color": 0xFF6B35, "hex": "#FF6B35", "party": 4},
    "reload_solo":   {"name": "Reload Solo",    "emoji": "🔄", "color": 0x00F5D4, "hex": "#00F5D4", "party": 1},
    "reload_cup":    {"name": "Reload Cup",     "emoji": "🏅", "color": 0xF72585, "hex": "#F72585", "party": 4},
    "settings_duos": {"name": "Settings Duos",  "emoji": "⚙️", "color": 0x7B2FFF, "hex": "#7B2FFF", "party": 2},
    "end_game":      {"name": "End Game",       "emoji": "💀", "color": 0xFF4560, "hex": "#FF4560", "party": 4},
    "reals_1v1":     {"name": "1v1 Reals",     "emoji": "🎯", "color": 0xFFD60A, "hex": "#FFD60A", "party": 1},
    "pro_reals":     {"name": "1v1 Pro Reals",  "emoji": "🏆", "color": 0xC0C0C0, "hex": "#C0C0C0", "party": 1},
}

DEFAULT = {
    "token": ENV_TOKEN,
    "guild_id": "",
    "scrim_channel_id": "",
    "invite_link": "",
    "command_prefix": "!",
    "host_name": "Ocean Scrims",
    "platforms": "PC / Windows, PlayStation, Xbox, Mobile",
    "verification_required": True,
    # Scrim priority role tiers  [[role_id, ...], ...]
    "scrim_priority_roles": [],
    # Schedule
    "schedule_enabled": False,
    "schedule_channel_id": "",
    "schedule_scrim_type": "solos",
    "schedule_interval": 30,
    "schedule_start_time": "00:00",
    "schedule_links": "",
    # Commands
    "commands": {
        "solos": "solos", "duos": "duos", "trios": "trios", "squads": "squads",
        "reload_solo": "reloadsolo", "reload_cup": "reloadcup",
        "settings_duos": "settingsduos", "end_game": "endgame",
        "reals_1v1": "1v1reals", "pro_reals": "1v1proreals",
        "concluded": "concluded",
        "started": "started",
        "invite": "invite",
    },
    "start_messages": {
        "solos":         "@everyone 🔫 **Solo Scrims** are now LIVE! Get in lobbies! 🎮",
        "duos":          "@everyone 👥 **Duos Scrims** are now LIVE! Grab your duo! 🎮",
        "trios":         "@everyone 🔱 **Trios Scrims** are now LIVE! Squad up x3! 🎮",
        "squads":        "@everyone ⚔️ **Squads Scrims** are now LIVE! Full squad up! 🎮",
        "reload_solo":   "@everyone 🔄 **Reload Solo Scrims** are now LIVE! 🎮",
        "reload_cup":    "@everyone 🏅 **Reload Cup** is now LIVE! Squad up for the cup! 🎮",
        "settings_duos": "@everyone ⚙️ **Settings Duos** are now LIVE! Match your duo's settings! 🎮",
        "end_game":      "@everyone 💀 **End Game Scrims** are now LIVE! Final circles only! 🎮",
        "reals_1v1":     "@everyone 🎯 **1v1 Reals** are now LIVE! Best players step up! 🎮",
        "pro_reals":     "@everyone 🏆 **1v1 Pro Reals** are now LIVE! Pros only! 🎮",
    },
    "concluded_line1": "Games will resume **AFTER DOWNTIME ENDS!**",
    "concluded_line2": "**SEE YOU THEN :)**",
    "concluded_line3": "Make sure to invite your friends,",
    # Dispatch customization
    "dispatch_title_prefix": "🚨",
    "dispatch_title_suffix": "🚨",
    "dispatch_intro": "**The lobby is live — get in!**",
    "dispatch_missed": "🟥  **Missed queue?** — React ✋ below to sign up late",
    "dispatch_signed": "⭕  **Already signed up?** — Ignore this message",
    # Verify / Epic OAuth
    "verify_channel_id": "",
    "base_url": f"http://localhost:{PORT}",
    "epic_client_id": "",
    "epic_client_secret": "",
    "verified_users": [],
    "active_scrim_label": "",
    "game_number": 0,
    "max_games": 0,
    "last_next_game_msg_id": None,
    "last_next_game_ch_id": None,
    "active_scrim": None,
    "active_scrim_started": None,
    "active_scrim_message_id": None,
    "active_dispatch_message_id": None,
    "dispatched": False,
    "signups": [],
    "missed_signups": [],
}


def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            saved = json.load(f)
        result = dict(DEFAULT)
        for k, v in saved.items():
            if isinstance(v, dict) and k in result and isinstance(result[k], dict):
                result[k] = {**result[k], **v}
            else:
                result[k] = v
        # Always prefer env var token over stored empty token
        if not result.get("token") and ENV_TOKEN:
            result["token"] = ENV_TOKEN
        return result
    return dict(DEFAULT)


def save_settings(s):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(s, f, indent=2)


GUILDS_DIR = os.path.join(DATA_DIR, "guilds")

def _home_guild_id():
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE) as f:
                return str(json.load(f).get("guild_id", ""))
    except Exception:
        pass
    return ""

def load_guild_settings(guild_id):
    """Load settings for a guild. Home guild uses main settings.json."""
    gid = str(guild_id)
    if gid == _home_guild_id() or not gid:
        return load_settings()
    path = os.path.join(GUILDS_DIR, f"{gid}.json")
    if os.path.exists(path):
        with open(path) as f:
            saved = json.load(f)
        result = dict(DEFAULT)
        for k, v in saved.items():
            if isinstance(v, dict) and k in result and isinstance(result[k], dict):
                result[k] = {**result[k], **v}
            else:
                result[k] = v
        return result
    return dict(DEFAULT)

def save_guild_settings(guild_id, s):
    """Save settings for a guild. Home guild uses main settings.json."""
    gid = str(guild_id)
    if gid == _home_guild_id() or not gid:
        save_settings(s)
        return
    os.makedirs(GUILDS_DIR, exist_ok=True)
    with open(os.path.join(GUILDS_DIR, f"{gid}.json"), "w") as f:
        json.dump(s, f, indent=2)


def _get_credentials():
    """Return (username, password_hash) from env vars or settings file."""
    if LOGIN_USERNAME and LOGIN_PASSWORD:
        return LOGIN_USERNAME, None, LOGIN_PASSWORD  # (user, hash, plain)
    s = load_settings()
    return s.get("account_username", ""), s.get("account_password_hash", ""), None


def _account_exists():
    if LOGIN_USERNAME and LOGIN_PASSWORD:
        return True
    s = load_settings()
    return bool(s.get("account_password_hash"))


def _check_login(username, password):
    """Return 'admin', 'host', or None."""
    # Check admin credentials
    if LOGIN_USERNAME and LOGIN_PASSWORD:
        if username == LOGIN_USERNAME and password == LOGIN_PASSWORD:
            return "admin"
    else:
        s = load_settings()
        stored_user = s.get("account_username", "")
        stored_hash = s.get("account_password_hash", "")
        if stored_hash and username == stored_user and check_password_hash(stored_hash, password):
            return "admin"
    # Check scrim host password (any username)
    s = load_settings()
    host_hash = s.get("scrim_host_password_hash", "")
    if host_hash and check_password_hash(host_hash, password):
        return "host"
    return None


def build_signup_embed(scrim_key, settings, guild=None):
    scrim = SCRIMS[scrim_key]
    label = settings.get("active_scrim_label", "")
    label_str = f" — {label.title()}" if label else ""
    embed = discord.Embed(title=f"Tournament Matchmaking{label_str}", color=scrim["color"])
    embed.description = (
        "A new custom match has been opened!\n"
        "**Please click ✋ to sign up for the match.**\n\n"
        "Make sure to have the correct amount of players in your party."
    )

    priority_tiers = settings.get("scrim_priority_roles", [])
    if priority_tiers:
        lines = []
        for i, tier in enumerate(priority_tiers, 1):
            role_ids = [r for r in tier if r]
            if role_ids:
                lines.append(f"{i}. " + ", ".join(f"<@&{rid}>" for rid in role_ids))
        if lines:
            embed.add_field(name="Scrim Priority", value="\n".join(lines), inline=False)

    mode_val = f"{scrim['emoji']} {scrim['name']}{label_str} Scrims"
    embed.add_field(name="Game Mode", value=mode_val, inline=False)
    embed.add_field(name="Players in your party", value=str(scrim["party"]), inline=False)
    if settings.get("verification_required", True):
        embed.add_field(name="⚠️  Verification required  ⚠️",
                        value="All members of your team must be verified on this server.", inline=False)
    embed.add_field(name="Allowed Platforms", value=settings.get("platforms", "PC / Windows, PlayStation, Xbox, Mobile"), inline=False)
    if guild and guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    host = settings.get("host_name", "Ocean Scrims")
    embed.set_footer(text=f"\U0001f30a Ocean Scrims  •  Host: {host}")
    return embed


async def send_concluded_embed(channel, scrim_key, settings):
    scrim = SCRIMS[scrim_key]
    invite = settings.get("invite_link", "")
    embed = discord.Embed(title=f"{scrim['name']} Scrims Have Concluded", color=scrim["color"])
    parts = []
    for attr in ("concluded_line1", "concluded_line2"):
        v = settings.get(attr, "")
        if v:
            if parts:
                parts.append("")
            parts.append(v)
    l3 = settings.get("concluded_line3", "")
    if l3:
        parts.append("")
        parts.append(f"• {l3}{(' ' + invite) if invite else ''}")
    embed.description = "\n".join(parts)
    if channel.guild.icon:
        embed.set_thumbnail(url=channel.guild.icon.url)
    embed.set_footer(text="\U0001f30a Ocean Scrims")
    await channel.send(embed=embed)
    if invite:
        await channel.send(invite)


def _time_str_to_ts(time_str):
    """'HH:MM' → unix timestamp for that time today (or tomorrow if already past)."""
    try:
        h, m = map(int, time_str.strip().split(":"))
    except Exception:
        return None
    now = datetime.now()
    target = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return int(target.timestamp())


def _start_offset_mins(start_time_str):
    try:
        h, m = start_time_str.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 0


def _next_interval_ts(interval_mins, start_time_str="00:00"):
    """Next interval-aligned local timestamp, always in the future."""
    offset = _start_offset_mins(start_time_str)
    now = datetime.now()
    total_mins = now.hour * 60 + now.minute
    mins_since_mark = (total_mins - offset) % interval_mins
    mins_to_next = interval_mins - mins_since_mark
    if mins_to_next == 0 or mins_to_next == interval_mins:
        mins_to_next = interval_mins
    nxt = (now + timedelta(minutes=mins_to_next)).replace(second=0, microsecond=0)
    ts = int(nxt.timestamp())
    now_ts = int(now.timestamp())
    while ts <= now_ts + 60:
        ts += interval_mins * 60
    return ts


def _secs_until_next_interval(interval_mins, start_time_str="00:00"):
    """Seconds until next interval mark using local time."""
    offset = _start_offset_mins(start_time_str)
    now = datetime.now()
    total_mins = now.hour * 60 + now.minute
    mins_since_mark = (total_mins - offset) % interval_mins
    secs_since_mark = mins_since_mark * 60 + now.second
    wait = interval_mins * 60 - secs_since_mark
    return wait if wait >= 10 else wait + interval_mins * 60


class _URLView(discord.ui.View):
    """Generic single URL-button view."""
    def __init__(self, label, url, emoji=None):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(label=label, url=url, emoji=emoji, style=discord.ButtonStyle.link))


class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Link Epic Account", emoji="🖐️", style=discord.ButtonStyle.primary, custom_id="verify:link_epic")
    async def link_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = load_settings()
        client_id = s.get("epic_client_id", "").strip()
        base_url  = s.get("base_url", f"http://localhost:{PORT}").rstrip("/")
        guild     = interaction.guild
        guild_name = guild.name if guild else "Ocean Scrims"
        guild_icon = guild.icon.url if guild and guild.icon else None
        user_id    = str(interaction.user.id)
        username   = interaction.user.display_name

        token = secrets.token_urlsafe(20)
        PENDING_VERIFICATIONS[token] = {
            "user_id":    user_id,
            "username":   username,
            "guild_name": guild_name,
            "guild_icon": guild_icon,
        }

        # DM button → our verify page, which opens Epic login as a popup.
        # When the popup closes, the countdown starts automatically.
        verify_url = f"{base_url}/verify/complete/{token}"
        epic_login = verify_url  # page itself handles opening Epic

        embed = discord.Embed(color=0x00D4FF)
        embed.set_author(name=f"{guild_name}  •  Epic Verification", icon_url=guild_icon)
        embed.title = "🔗  Link Your Epic Account"
        embed.description = (
            f"Click **Sign in with Epic** to log into your Epic Games account.\n"
            f"After signing in you'll be automatically brought back and verified for **{guild_name}**.\n\n"
            f"⚠️  **This link is personal — do not share it.**"
        )
        embed.add_field(name="Server",  value=f"**{guild_name}**", inline=True)
        embed.add_field(name="Member",  value=f"**{username}**",   inline=True)
        embed.add_field(name="Expires", value="15 minutes",        inline=True)
        if guild_icon:
            embed.set_thumbnail(url=guild_icon)
        embed.set_footer(text="🌊 Ocean Scrims  •  Powered by Epic Games")
        embed.timestamp = datetime.utcnow()

        try:
            await interaction.user.send(embed=embed, view=_URLView("Sign in with Epic", epic_login, "🎮"))
            await interaction.response.send_message(
                "📬  Check your DMs — sign in with Epic to get verified!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌  I couldn't DM you. Please enable DMs from server members.", ephemeral=True)


class LeaderboardView(discord.ui.View):
    def __init__(self, guild_id: str, scrim_key=None):
        super().__init__(timeout=None)
        self.guild_id = str(guild_id)
        self.scrim_key = scrim_key

        btn_team = discord.ui.Button(label="Check your team", emoji="👤", style=discord.ButtonStyle.secondary)
        btn_team.callback = self._check_team
        self.add_item(btn_team)

        btn_lb = discord.ui.Button(label="Check leaderboard", emoji="🏆", style=discord.ButtonStyle.secondary)
        btn_lb.callback = self._check_leaderboard
        self.add_item(btn_lb)

    def _get_history(self, guild_id=None):
        s = load_guild_settings(guild_id or self.guild_id)
        key = self.scrim_key
        if key and key in SCRIMS:
            history = s.get("signup_history_by_mode", {}).get(key, {})
            if not history:
                history = s.get("signup_history", {})
        else:
            history = s.get("signup_history", {})
        return s, history

    async def _check_team(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id) if interaction.guild_id else self.guild_id
        s, history = self._get_history(gid)
        uid = str(interaction.user.id)
        player = history.get(uid)
        if not player:
            await interaction.response.send_message("📊 You have no stats recorded yet.", ephemeral=True)
            return

        sorted_uids = sorted(history, key=lambda u: history[u].get("score", history[u].get("count", 0) * 50), reverse=True)
        rank = sorted_uids.index(uid) + 1 if uid in sorted_uids else "?"
        games = player.get("count", 0)
        wins  = player.get("wins", 0)
        score = player.get("score", games * 50)

        embed = discord.Embed(title="📊 Your Stats", color=0x00B4D8)
        embed.add_field(name="Rank",  value=f"#{rank}",  inline=True)
        embed.add_field(name="Games", value=str(games),  inline=True)
        embed.add_field(name="Wins",  value=str(wins),   inline=True)
        embed.add_field(name="Score", value=str(score),  inline=True)
        embed.set_footer(text="🌊 Ocean Scrims")
        embed.timestamp = datetime.utcnow()

        try:
            await interaction.user.send(embed=embed)
            await interaction.response.send_message("📬 Check your DMs for your stats!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I couldn't DM you. Please enable DMs from server members.", ephemeral=True)

    async def _check_leaderboard(self, interaction: discord.Interaction):
        gid = str(interaction.guild_id) if interaction.guild_id else self.guild_id
        s, history = self._get_history(gid)
        now = datetime.utcnow()
        now_str = now.strftime("%m/%d/%Y")
        key = self.scrim_key

        if key and key in SCRIMS:
            scrim = SCRIMS[key]
            title_str = f"Leaderboard {scrim['name']} Scrims - {now_str}"
            color = scrim["color"]
        else:
            title_str = f"Leaderboard All Scrims - {now_str}"
            color = 0xFFB800

        if not history:
            await interaction.response.send_message("📊 No leaderboard data yet.", ephemeral=True)
            return

        players = sorted(history.values(), key=lambda x: x.get("score", x.get("count", 0) * 50), reverse=True)[:10]

        R, N, G, W, S = 2, 16, 6, 4, 5
        sep    = f"+{'-'*(R+2)}+{'-'*(N+2)}+{'-'*(G+2)}+{'-'*(W+2)}+{'-'*(S+2)}+"
        header = f"| {'#':<{R}} | {'Team Lead':^{N}} | {'Games':^{G}} | {'Wins':^{W}} | {'Score':^{S}} |"
        rows   = [sep, header, sep]
        for i, p in enumerate(players, 1):
            name  = p.get("username", "Unknown")
            if len(name) > N:
                name = name[:N-3] + "..."
            games = p.get("count", 0)
            wins  = p.get("wins", 0)
            score = p.get("score", games * 50)
            rows.append(f"| {i:>{R}} | {name:^{N}} | {games:^{G}} | {wins:^{W}} | {score:^{S}} |")
            rows.append("|")
        rows.append(sep)
        table = "```\n" + "\n".join(rows) + "\n```"

        embed = discord.Embed(title=title_str, color=color)
        embed.add_field(name="Teams",                        value=str(len(history)), inline=False)
        embed.add_field(name=f"Standings (Top {len(players)})", value=table,          inline=False)
        embed.set_footer(text="🌊 Ocean Scrims")
        embed.timestamp = now

        try:
            await interaction.user.send(embed=embed)
            await interaction.response.send_message("📬 Check your DMs for the leaderboard!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I couldn't DM you. Please enable DMs from server members.", ephemeral=True)


class BotManager:
    def __init__(self):
        self.bot = None
        self.loop = None
        self.thread = None
        self.bot_user = None
        self.last_error = None

    def is_running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, settings):
        if self.is_running():
            return
        self.last_error = None
        self.thread = threading.Thread(target=self._run, args=(settings,), daemon=True)
        self.thread.start()

    def stop(self):
        if self.loop and self.bot:
            asyncio.run_coroutine_threadsafe(self.bot.close(), self.loop)

    def fire(self, coro):
        if self.loop and self.is_running():
            asyncio.run_coroutine_threadsafe(coro, self.loop)
            return True
        return False

    def get_channels(self, guild_id):
        if not self.is_running() or not self.bot:
            return []
        async def _fetch():
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                return []
            return [{"id": str(c.id), "name": c.name} for c in guild.text_channels]
        try:
            return asyncio.run_coroutine_threadsafe(_fetch(), self.loop).result(timeout=5)
        except Exception:
            return []

    def _run(self, initial_settings):
        # ProactorEventLoop (Windows default) misreports SSL errors with aiohttp;
        # use SelectorEventLoop for the bot thread to avoid ssl:default [None] failures.
        if sys.platform == "win32":
            self.loop = asyncio.SelectorEventLoop()
        else:
            self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        ssl_ctx = ssl.create_default_context(cafile=certifi.where())

        async def _make_connector():
            return aiohttp.TCPConnector(ssl=ssl_ctx)

        connector = self.loop.run_until_complete(_make_connector())
        intents = discord.Intents.all()
        bot = commands.Bot(
            command_prefix=initial_settings.get("command_prefix", "!"),
            intents=intents,
            connector=connector,
        )
        self.bot = bot

        # ── Schedule loop ───────────────────────────────────────────────
        async def _post_schedule(cfg, override_scrim_key=None):
            ch_id = cfg.get("schedule_channel_id")
            if not ch_id:
                return
            ch = bot.get_channel(int(ch_id))
            if not ch:
                return

            interval = int(cfg.get("schedule_interval", 30))
            start_time = cfg.get("schedule_start_time", "00:00")
            next_ts = _next_interval_ts(interval, start_time)

            scrim_key = override_scrim_key or cfg.get("active_scrim") or cfg.get("schedule_scrim_type", "solos")
            scrim = SCRIMS.get(scrim_key, SCRIMS["solos"])
            links = cfg.get("schedule_links", "")
            count = len(cfg.get("signups", []))

            # ── Embed 1: Match Started ──────────────────────────────────
            started = discord.Embed(color=scrim["color"])
            player_line = f"Match Started at **{count} Players**" if count > 0 else "**Match Starting Now!**"
            started.description = player_line
            if links:
                started.description += f"\n\n{links}"
            started.set_footer(text="\U0001f30a Ocean Scrims")

            if os.path.exists(BANNER_PATH):
                started.set_image(url="attachment://ocean_banner.png")
                await ch.send(embed=started, file=discord.File(BANNER_PATH, filename="ocean_banner.png"))
            else:
                await ch.send(embed=started)

            # ── Embed 2: Next Game live countdown ───────────────────────
            # Delete the old NEXT GAME embed so it never shows a stale time
            old_msg_id = cfg.get("last_next_game_msg_id")
            old_ch_id = cfg.get("last_next_game_ch_id")
            if old_msg_id:
                try:
                    old_ch = bot.get_channel(int(old_ch_id)) if old_ch_id else ch
                    if old_ch:
                        old_msg = await old_ch.fetch_message(int(old_msg_id))
                        await old_msg.delete()
                except Exception:
                    pass

            next_embed = discord.Embed(color=0x00D4FF)
            next_embed.description = (
                f"**NEXT GAME!**  {scrim['emoji']}\n"
                f"<t:{next_ts}:T>  ·  <t:{next_ts}:R>"
            )
            next_msg = await ch.send(embed=next_embed)

            s2 = load_settings()
            s2["last_next_game_msg_id"] = str(next_msg.id)
            s2["last_next_game_ch_id"] = str(ch.id)
            save_settings(s2)

        async def schedule_loop():
            await asyncio.sleep(3)
            while True:
                try:
                    cfg = load_settings()
                    interval = int(cfg.get("schedule_interval", 30))
                    start_time = cfg.get("schedule_start_time", "00:00")
                    wait = _secs_until_next_interval(interval, start_time)
                    await asyncio.sleep(wait)

                    cfg = load_settings()  # Re-read after sleeping
                    if cfg.get("schedule_enabled") and cfg.get("schedule_channel_id"):
                        await _post_schedule(cfg)
                except asyncio.CancelledError:
                    return
                except Exception as e:
                    print(f"Schedule error: {e}")
                    await asyncio.sleep(60)

        # ── Bot events ──────────────────────────────────────────────────
        _owner_id = None

        @bot.event
        async def on_ready():
            nonlocal _owner_id
            self.bot_user = str(bot.user)
            print(f"Bot online: {bot.user}")
            bot.add_view(VerifyView())
            asyncio.get_running_loop().create_task(schedule_loop())
            try:
                app_info = await bot.application_info()
                _owner_id = app_info.owner.id
            except Exception:
                pass

        @bot.event
        async def on_message(message):
            if message.author.bot:
                return

            # DM reply → set Fortnite nickname
            if message.guild is None:
                uid = str(message.author.id)
                if uid in PENDING_NICKNAME:
                    info = PENDING_NICKNAME.pop(uid)
                    fortnite_name = message.content.strip()
                    if not fortnite_name or len(fortnite_name) > 32:
                        await message.reply("❌ Please send just your Fortnite username (max 32 characters).")
                        PENDING_NICKNAME[uid] = info
                        return

                    renamed = False
                    fail_reason = ""
                    guild_id_str = info.get("guild_id", "")

                    if not guild_id_str:
                        fail_reason = "Guild ID not configured in bot settings."
                    else:
                        try:
                            guild = bot.get_guild(int(guild_id_str))
                            if not guild:
                                fail_reason = f"Bot is not in guild {guild_id_str}."
                            else:
                                try:
                                    member = guild.get_member(message.author.id)
                                    if member is None:
                                        member = await guild.fetch_member(message.author.id)
                                except discord.NotFound:
                                    fail_reason = "You are not in the server."
                                    member = None

                                if member:
                                    if guild.owner_id == member.id:
                                        fail_reason = "Server owners cannot have their nickname changed by a bot."
                                    else:
                                        try:
                                            await member.edit(nick=fortnite_name, reason="Ocean Scrims verification")
                                            renamed = True
                                        except discord.Forbidden:
                                            bot_member = guild.get_member(bot.user.id)
                                            bot_top = bot_member.top_role.position if bot_member else 0
                                            mem_top = member.top_role.position
                                            if mem_top >= bot_top:
                                                fail_reason = f"Your highest role is above or equal to the bot's role. Move the bot's role higher in Server Settings → Roles."
                                            else:
                                                fail_reason = "Missing permissions despite having admin — check role hierarchy."
                                        except discord.HTTPException as e:
                                            fail_reason = f"Discord error: {e}"
                        except Exception as e:
                            fail_reason = str(e)

                    # Always save the name regardless of rename success
                    s2 = load_settings()
                    for v in s2.get("verified_users", []):
                        if v["user_id"] == uid:
                            v["epic_name"] = fortnite_name
                    save_settings(s2)

                    confirm = discord.Embed(color=0x00FF94 if renamed else 0xFF6B00)
                    if renamed:
                        confirm.title = "🎮  Nickname Set!"
                        confirm.description = f"Your server nickname has been set to **{fortnite_name}**."
                    else:
                        confirm.title = "⚠️  Couldn't Rename You"
                        confirm.description = f"Your Fortnite name **{fortnite_name}** has been saved, but the nickname couldn't be applied.\n\n**Reason:** {fail_reason}"
                    await message.reply(embed=confirm)
                    return

            if message.guild is None:
                return
            gid = str(message.guild.id)

            # Owner-only leave command — works in any server, any channel
            if message.content.strip().lower() == "!leave" and _owner_id and message.author.id == _owner_id:
                await message.reply("👋 Leaving. Bye!")
                await message.guild.leave()
                return

            s = load_guild_settings(gid)
            prefix = s.get("command_prefix", "!")
            if not message.content.startswith(prefix):
                return
            raw = message.content[len(prefix):].strip()
            cmd = raw.lower().split()[0] if raw.split() else ""
            parts = raw.split()

            # ── Admin setup commands ────────────────────────────────────
            is_admin = message.author.guild_permissions.administrator
            if cmd == "setscrimchannel" and is_admin:
                try:
                    s["scrim_channel_id"] = str(message.channel.id)
                    os.makedirs(GUILDS_DIR, exist_ok=True)
                    save_guild_settings(gid, s)
                    await message.reply(f"✅ Scrim channel set to **#{message.channel.name}**.\nUse `{prefix}solos`, `{prefix}duos` etc. to start scrims.")
                except Exception as e:
                    await message.reply(f"❌ Setup failed: `{e}`")
                return
            if cmd == "setprefix" and is_admin:
                new_prefix = parts[1] if len(parts) > 1 else "!"
                s["command_prefix"] = new_prefix[:3]
                save_guild_settings(gid, s)
                await message.reply(f"✅ Prefix changed to `{new_prefix}`.")
                return

            cmds = s.get("commands", {})

            def _match_key(word):
                w = word.lower()
                for k in SCRIMS:
                    if w in (k, cmds.get(k, "").lower(),
                             SCRIMS[k]["name"].lower().replace(" ", "")):
                        return k
                return None

            for scrim_key in SCRIMS:
                if cmd == cmds.get(scrim_key, "").lower():
                    # !solos [label...]  e.g. !solos silvers
                    label = " ".join(parts[1:]).title() if len(parts) > 1 else ""
                    s["active_scrim_label"] = label
                    save_guild_settings(gid, s)
                    try:
                        await message.add_reaction("✅")
                    except Exception:
                        pass
                    try:
                        await _start_scrim(message.channel, s, scrim_key, gid)
                    except Exception as e:
                        import traceback
                        err = traceback.format_exc()
                        print(f"_start_scrim error: {err}")
                        try:
                            await message.channel.send(f"❌ Error: `{e}`")
                        except Exception:
                            pass
                    return

            if cmd == cmds.get("concluded", "concluded").lower():
                # !concluded [gamemode] [label...]
                if len(parts) > 1:
                    key = _match_key(parts[1])
                    if key:
                        s["active_scrim"] = key
                        s["active_scrim_label"] = " ".join(parts[2:]).title() if len(parts) > 2 else ""
                    else:
                        s["active_scrim_label"] = " ".join(parts[1:]).title()
                await _conclude(message.channel, s, gid)
                return

            if cmd == cmds.get("started", "started").lower():
                # !started [gamemode] [label...] <count> [time]
                count = 0
                next_game_time = None
                num_idx = None
                for i, p in enumerate(parts[1:], 1):
                    if p.isdigit():
                        count = int(p)
                        num_idx = i
                        if i + 1 < len(parts) and ":" in parts[i + 1]:
                            next_game_time = parts[i + 1]
                        break
                pre = parts[1:num_idx] if num_idx is not None else parts[1:]
                if pre:
                    key = _match_key(pre[0])
                    if key:
                        s["active_scrim"] = key
                        s["active_scrim_label"] = " ".join(pre[1:]).title() if len(pre) > 1 else ""
                    else:
                        s["active_scrim_label"] = " ".join(pre).title()
                save_guild_settings(gid, s)
                await _post_started(message.channel, s, count, next_game_time=next_game_time, guild_id=gid)
                return

            if cmd == cmds.get("invite", "invite").lower():
                await _post_invite(message.channel, s)
                return

            if cmd == "dispatch":
                # !dispatch <code>  — code is everything after dispatch
                code = " ".join(parts[1:]).strip() if len(parts) > 1 else ""
                if not code:
                    await message.channel.send("Usage: `!dispatch <match code>`  e.g. `!dispatch ocean-5421`", delete_after=8)
                    return
                await _do_dispatch(message.channel, s, code, gid)
                return

            if cmd == "leaderboards":
                mode_arg = parts[1] if len(parts) > 1 else None
                scrim_key = _match_key(mode_arg) if mode_arg else s.get("active_scrim")
                await _post_leaderboards(message.channel, s, scrim_key)
                return

            if cmd == "pts":
                if not is_admin:
                    return
                if len(parts) < 3:
                    await message.channel.send("Usage: `!pts <username> <points>`", delete_after=8)
                    return
                target = parts[1]
                try:
                    amount = int(parts[2])
                except ValueError:
                    await message.channel.send("❌ Points must be a number.", delete_after=8)
                    return
                history = s.get("signup_history", {})
                uid = next((k for k, v in history.items() if v.get("username", "").lower() == target.lower()), None)
                if uid is None:
                    uid = f"manual_{target.lower()}"
                    history[uid] = {"username": target, "count": 0, "score": 0, "wins": 0}
                entry = history[uid]
                entry["score"] = entry.get("score", entry.get("count", 0) * 50) + amount
                history[uid] = entry
                s["signup_history"] = history
                save_guild_settings(gid, s)
                await message.reply(f"✅ **{entry['username']}** — **{entry['score']}** points")
                return

            if cmd == "win":
                if not is_admin:
                    return
                if len(parts) < 2:
                    await message.channel.send("Usage: `!win <username>`", delete_after=8)
                    return
                target = parts[1]
                history = s.get("signup_history", {})
                uid = next((k for k, v in history.items() if v.get("username", "").lower() == target.lower()), None)
                if uid is None:
                    uid = f"manual_{target.lower()}"
                    history[uid] = {"username": target, "count": 0, "score": 0, "wins": 0}
                entry = history[uid]
                entry["wins"] = entry.get("wins", 0) + 1
                history[uid] = entry
                s["signup_history"] = history
                save_guild_settings(gid, s)
                await message.reply(f"✅ **{entry['username']}** — **{entry['wins']}** win(s)")
                return

            if cmd == "epic":
                ch_id = s.get("verify_channel_id", "")
                ch = bot.get_channel(int(ch_id)) if ch_id else None
                # Never post verify embed in a channel from a different guild
                if ch and ch.guild.id != message.guild.id:
                    ch = None
                ch = ch or message.channel
                embed = discord.Embed(
                    title="Epic Account Verification",
                    description=(
                        "Please click on the raised hand below to link your Epic Account. "
                        "You will receive a direct message from the bot with further instructions."
                    ),
                    color=0x00B4D8,
                )
                if ch.guild.icon:
                    embed.set_thumbnail(url=ch.guild.icon.url)
                embed.set_footer(text="\U0001f30a Ocean Scrims")
                await ch.send(embed=embed, view=VerifyView())
                if ch != message.channel:
                    await message.channel.send(f"✅ Verification embed posted in {ch.mention}!", delete_after=5)
                return

        async def _do_dispatch(channel, s, match_code, guild_id=None):
            gid   = str(guild_id or channel.guild.id)
            active = s.get("active_scrim")
            ch_id  = s.get("scrim_channel_id")
            fetched = bot.get_channel(int(ch_id)) if ch_id else None
            if fetched and fetched.guild.id != channel.guild.id:
                fetched = None
            ch = fetched or channel
            scrim  = SCRIMS.get(active, SCRIMS["solos"])
            snap   = dict(s)
            orig_msg_id = s.get("active_scrim_message_id")

            # Delete original sign-up message
            if orig_msg_id:
                try:
                    orig = await ch.fetch_message(int(orig_msg_id))
                    await orig.delete()
                except Exception:
                    pass

            # Colour-ramp animation (identical to dashboard)
            ramp_frames = [
                (0x06080A, "🔐  **Securing match...**"),
                (0x0A1018, "📡  **Broadcasting lobby...**"),
                (0x0D1A28, "🔓  **Code locked in...**"),
                (0x102238, "⚡  **Launching dispatch...**"),
                (scrim["color"], "🚀  **DISPATCHED!**"),
            ]
            init = discord.Embed(color=ramp_frames[0][0])
            init.description = ramp_frames[0][1]
            init.set_footer(text="\U0001f30a Ocean Scrims")
            msg = await ch.send("@everyone", embed=init)
            for color, desc in ramp_frames[1:]:
                await asyncio.sleep(0.7)
                fr = discord.Embed(color=color)
                fr.description = desc
                fr.set_footer(text="\U0001f30a Ocean Scrims")
                await msg.edit(embed=fr)
            await asyncio.sleep(0.5)

            # Dispatch embed
            d_prefix = snap.get("dispatch_title_prefix", "🚨").strip()
            d_suffix = snap.get("dispatch_title_suffix", "🚨").strip()
            d_intro  = snap.get("dispatch_intro",  "**The lobby is live — get in!**")
            d_missed = snap.get("dispatch_missed", "🟥  **Missed queue?** — React ✋ below to sign up late")
            d_signed = snap.get("dispatch_signed", "⭕  **Already signed up?** — Ignore this message")
            title_parts = [p for p in [d_prefix, f"{scrim['emoji']}  {scrim['name'].upper()} DISPATCH", d_suffix] if p]
            embed = discord.Embed(
                title="  ".join(title_parts),
                color=scrim["color"],
            )
            embed.description = f"{d_intro}\n\n{d_missed}\n{d_signed}\n\n🔑  **Match Key**\n```\n{match_code}\n```"
            embed.set_footer(text="\U0001f30a Ocean Scrims")
            await msg.edit(embed=embed)
            await msg.add_reaction("✋")
            s2 = load_guild_settings(gid)
            s2["active_dispatch_message_id"] = str(msg.id)
            s2["active_scrim_message_id"] = None
            s2["missed_signups"] = []
            s2["dispatched"] = True
            save_guild_settings(gid, s2)

        async def _post_leaderboards(channel, s, scrim_key=None):
            now = datetime.utcnow()
            now_str = now.strftime("%m/%d/%Y")

            if scrim_key and scrim_key in SCRIMS:
                scrim = SCRIMS[scrim_key]
                mode_history = s.get("signup_history_by_mode", {}).get(scrim_key, {})
                if not mode_history:
                    mode_history = s.get("signup_history", {})
                title_str = f"Leaderboard {scrim['name']} Scrims - {now_str}"
                color = scrim["color"]
            else:
                mode_history = s.get("signup_history", {})
                title_str = f"Leaderboard All Scrims - {now_str}"
                color = 0xFFB800

            if not mode_history:
                await channel.send("📊 No leaderboard data yet.")
                return

            players = sorted(
                mode_history.values(),
                key=lambda x: x.get("score", x.get("count", 0) * 50),
                reverse=True
            )[:10]

            R, N, G, W, S = 2, 16, 6, 4, 5
            sep = f"+{'-'*(R+2)}+{'-'*(N+2)}+{'-'*(G+2)}+{'-'*(W+2)}+{'-'*(S+2)}+"
            header = f"| {'#':<{R}} | {'Team Lead':^{N}} | {'Games':^{G}} | {'Wins':^{W}} | {'Score':^{S}} |"

            rows = [sep, header, sep]
            for i, p in enumerate(players, 1):
                name = p.get("username", "Unknown")
                if len(name) > N:
                    name = name[:N-3] + "..."
                games = p.get("count", 0)
                wins  = p.get("wins", 0)
                score = p.get("score", games * 50)
                rows.append(f"| {i:>{R}} | {name:^{N}} | {games:^{G}} | {wins:^{W}} | {score:^{S}} |")
                rows.append("|")
            rows.append(sep)

            table = "```\n" + "\n".join(rows) + "\n```"

            embed = discord.Embed(title=title_str, color=color)

            invite = s.get("invite_link", "")
            if invite:
                embed.add_field(name="Server Invite Link 🔗", value=invite, inline=False)

            started = s.get("active_scrim_started")
            if started:
                try:
                    ts = int(datetime.fromisoformat(started).timestamp())
                    embed.add_field(name="Start", value=f"<t:{ts}:F>", inline=True)
                    embed.add_field(name="End",   value="—",            inline=True)
                except Exception:
                    pass

            embed.add_field(name="Teams",                        value=str(len(mode_history)), inline=False)
            embed.add_field(name=f"Standings (Top {len(players)})", value=table,              inline=False)

            if channel.guild.icon:
                embed.set_thumbnail(url=channel.guild.icon.url)
            embed.set_footer(text="\U0001f30a Ocean Scrims")
            embed.timestamp = now

            gid = str(channel.guild.id) if channel.guild else ""
            view = LeaderboardView(gid, scrim_key)
            await channel.send(embed=embed, view=view)

        async def _post_started(source_channel, s, player_count, next_game_time=None, guild_id=None):
            gid = str(guild_id or (source_channel.guild.id if source_channel and source_channel.guild else ""))
            ch_id = s.get("schedule_channel_id") or s.get("scrim_channel_id")
            ch = (bot.get_channel(int(ch_id)) if ch_id else None) or source_channel
            if not ch:
                return

            # Increment game counter
            s2 = load_guild_settings(gid)
            s2["game_number"] = s2.get("game_number", 0) + 1
            game_num = s2["game_number"]
            max_games = int(s2.get("max_games", 0))
            save_guild_settings(gid, s2)

            interval = int(s.get("schedule_interval", 30))
            start_time = s.get("schedule_start_time", "00:00")

            # Use manually provided time, otherwise auto-calculate
            next_ts = (_time_str_to_ts(next_game_time) if next_game_time else None) or _next_interval_ts(interval, start_time)

            scrim_key = s.get("active_scrim") or s.get("schedule_scrim_type", "solos")
            scrim = SCRIMS.get(scrim_key, SCRIMS["solos"])

            embed = discord.Embed(color=scrim["color"])
            icon_url = ch.guild.icon.url if ch.guild.icon else None
            embed.set_author(name="OCEAN SCRIMS — STARTED", icon_url=icon_url)

            count_line = f"**{player_count} Players**" if player_count > 0 else "**Players**"
            game_line = f"\n\nGame **{game_num}**" + (f" of **{max_games}**" if max_games > 0 else "")
            embed.description = (
                f"Match Started at\n"
                f"{count_line}"
                f"{game_line}\n\n"
                f"**Next Game**\n"
                f"<t:{next_ts}:T> · <t:{next_ts}:R>"
            )

            # Delete old NEXT GAME embed and dispatch embed before posting new one
            s3 = load_settings()

            dispatch_msg_id = s3.get("active_dispatch_message_id")
            dispatch_ch_id = s3.get("scrim_channel_id")
            if dispatch_msg_id:
                try:
                    dispatch_ch = bot.get_channel(int(dispatch_ch_id)) if dispatch_ch_id else ch
                    if dispatch_ch:
                        dispatch_msg = await dispatch_ch.fetch_message(int(dispatch_msg_id))
                        await dispatch_msg.delete()
                except Exception:
                    pass
                s3["active_dispatch_message_id"] = None
                s3["dispatched"] = False

            old_msg_id = s3.get("last_next_game_msg_id")
            old_ch_id = s3.get("last_next_game_ch_id")
            if old_msg_id:
                try:
                    old_ch2 = bot.get_channel(int(old_ch_id)) if old_ch_id else ch
                    if old_ch2:
                        old_msg = await old_ch2.fetch_message(int(old_msg_id))
                        await old_msg.delete()
                except Exception:
                    pass

            if os.path.exists(BANNER_PATH):
                embed.set_image(url="attachment://ocean_banner.png")
                sent = await ch.send(embed=embed, file=discord.File(BANNER_PATH, filename="ocean_banner.png"))
            else:
                sent = await ch.send(embed=embed)

            s3["last_next_game_msg_id"] = str(sent.id)
            s3["last_next_game_ch_id"] = str(ch.id)
            save_guild_settings(gid, s3)

            # Auto-conclude when max games reached
            if max_games > 0 and game_num >= max_games:
                s3 = load_guild_settings(gid)
                if s3.get("active_scrim") and s3.get("scrim_channel_id"):
                    conclude_ch = bot.get_channel(int(s3["scrim_channel_id"]))
                    if conclude_ch:
                        await send_concluded_embed(conclude_ch, s3["active_scrim"], s3)
                s3["active_scrim"] = None
                s3["active_scrim_started"] = None
                s3["active_scrim_message_id"] = None
                s3["game_number"] = 0
                save_guild_settings(gid, s3)

        async def _post_invite(channel, s):
            invite = s.get("invite_link", "")
            if not invite:
                await channel.send("No invite link configured — set one in Settings.", delete_after=8)
                return
            embed = discord.Embed(color=0x00D4FF)
            embed.title = "\U0001f30a  Join Ocean Scrims!"
            embed.description = (
                "Looking for a server to play custom scrims?\n"
                "**We run daily customs — all platforms welcome!**\n\n"
                f"[**→  Click here to join**]({invite})\n"
                f"`{invite}`"
            )
            embed.add_field(name="🖥️  Platforms", value=s.get("platforms", "PC / Windows, PlayStation, Xbox, Mobile"), inline=False)
            embed.add_field(name="🎙️  Hosted by", value=f"**{s.get('host_name', 'Ocean Scrims')}**", inline=False)
            if channel.guild.icon:
                embed.set_thumbnail(url=channel.guild.icon.url)
            embed.set_footer(text="\U0001f30a Ocean Scrims")
            embed.timestamp = datetime.utcnow()
            await channel.send("@everyone", embed=embed)

        self._post_invite = _post_invite

        # Store for Flask access
        self._post_started = _post_started

        @bot.event
        async def on_guild_join(guild):
            prefix = "!"
            embed = discord.Embed(color=0x00D4FF)
            embed.title = "🌊  Thanks for adding Ocean Scrims Helper!"
            embed.description = (
                f"To get started, have an **admin** type in your scrim channel:\n\n"
                f"`{prefix}setscrimchannel`\n\n"
                f"This sets the channel where scrims are posted. Then use:\n"
                f"`{prefix}solos` `{prefix}duos` `{prefix}trios` `{prefix}squads`\n\n"
                f"**Other setup commands:**\n"
                f"`{prefix}setprefix <symbol>` — change the command prefix"
            )
            embed.set_footer(text="🌊 Ocean Scrims  •  Type !setscrimchannel to begin")
            for ch in guild.text_channels:
                try:
                    await ch.send(embed=embed)
                    break
                except Exception:
                    continue

        @bot.event
        async def on_raw_reaction_add(payload):
            if payload.user_id == bot.user.id:
                return
            gid = str(payload.guild_id)
            s = load_guild_settings(gid)
            guild = bot.get_guild(payload.guild_id)
            member = guild.get_member(payload.user_id) if guild else None
            uname = member.display_name if member else str(payload.user_id)

            # ✋ sign-up on the open message
            if str(payload.message_id) == str(s.get("active_scrim_message_id")):
                if str(payload.emoji) == "✋":
                    signups = s.get("signups", [])
                    if not any(su["user_id"] == str(payload.user_id) for su in signups):
                        signups.append({
                            "user_id": str(payload.user_id),
                            "username": uname,
                            "timestamp": datetime.utcnow().isoformat(),
                        })
                        s["signups"] = signups
                        # Track for leaderboard
                        history = s.get("signup_history", {})
                        uid_str = str(payload.user_id)
                        entry = history.get(uid_str, {"username": uname, "count": 0})
                        entry["count"] += 1
                        entry["username"] = uname
                        history[uid_str] = entry
                        s["signup_history"] = history
                        mode_key = s.get("active_scrim")
                        if mode_key:
                            mode_hist = s.get("signup_history_by_mode", {})
                            if mode_key not in mode_hist:
                                mode_hist[mode_key] = {}
                            m = mode_hist[mode_key].get(uid_str, {"username": uname, "count": 0, "wins": 0})
                            m["count"] += 1
                            m["username"] = uname
                            mode_hist[mode_key][uid_str] = m
                            s["signup_history_by_mode"] = mode_hist
                        save_guild_settings(gid, s)

            # ✋ missed-out on the dispatch message
            elif str(payload.message_id) == str(s.get("active_dispatch_message_id")):
                if str(payload.emoji) == "✋":
                    missed = s.get("missed_signups", [])
                    if not any(m["user_id"] == str(payload.user_id) for m in missed):
                        missed.append({
                            "user_id": str(payload.user_id),
                            "username": uname,
                            "timestamp": datetime.utcnow().isoformat(),
                        })
                        s["missed_signups"] = missed
                        save_guild_settings(gid, s)

        @bot.event
        async def on_raw_reaction_remove(payload):
            gid = str(payload.guild_id)
            s = load_guild_settings(gid)
            emoji = str(payload.emoji)

            if emoji == "✋" and str(payload.message_id) == str(s.get("active_scrim_message_id")):
                s["signups"] = [su for su in s.get("signups", []) if su["user_id"] != str(payload.user_id)]
                save_guild_settings(gid, s)

            elif emoji == "✋" and str(payload.message_id) == str(s.get("active_dispatch_message_id")):
                s["missed_signups"] = [m for m in s.get("missed_signups", []) if m["user_id"] != str(payload.user_id)]
                save_guild_settings(gid, s)

        async def _start_scrim(channel, s, scrim_key, guild_id=None):
            ch_id = s.get("scrim_channel_id")
            fetched = bot.get_channel(int(ch_id)) if ch_id else None
            # Never post in a channel that belongs to a different guild
            if fetched and channel and hasattr(channel, "guild") and fetched.guild.id != channel.guild.id:
                fetched = None
            target = fetched or channel
            s["active_scrim"] = scrim_key
            s["active_scrim_started"] = datetime.utcnow().isoformat()
            s["signups"] = []
            s["active_scrim_message_id"] = None
            save_guild_settings(guild_id or target.guild.id, s)
            scrim = SCRIMS[scrim_key]
            loading = discord.Embed(color=scrim["color"])
            loading.description = "⠋  **Opening custom match...**"
            loading.set_footer(text="\U0001f30a Ocean Scrims")
            msg = await target.send("@everyone", embed=loading)
            for spinner, label in [
                ("⠙", "Setting up lobbies..."),
                ("⠹", "Preparing scrim..."),
                ("⠸", "Sign-ups opening soon..."),
                ("✅", "**Sign-ups are OPEN!**"),
            ]:
                await asyncio.sleep(0.65)
                frame = discord.Embed(color=scrim["color"])
                frame.description = f"{spinner}  **{label}**"
                frame.set_footer(text="\U0001f30a Ocean Scrims")
                await msg.edit(embed=frame)
            await asyncio.sleep(0.4)
            embed = build_signup_embed(scrim_key, s, target.guild)
            await msg.edit(embed=embed)
            await msg.add_reaction("✋")
            s["active_scrim_message_id"] = str(msg.id)
            save_guild_settings(guild_id or target.guild.id, s)

        async def _conclude(channel, s, guild_id=None):
            gid = str(guild_id or channel.guild.id)
            active = s.get("active_scrim")
            ch_id = s.get("scrim_channel_id")
            fetched = bot.get_channel(int(ch_id)) if ch_id else None
            if fetched and fetched.guild.id != channel.guild.id:
                fetched = None
            target = fetched or channel
            if not active or active not in SCRIMS:
                await channel.send("No active scrim to conclude.", delete_after=5)
                return
            await send_concluded_embed(target, active, s)
            s["active_scrim"] = None
            s["active_scrim_started"] = None
            s["active_scrim_message_id"] = None
            s["game_number"] = 0
            s["dispatched"] = False
            save_guild_settings(gid, s)

        # Store for Flask access
        self._post_schedule = _post_schedule
        self._post_leaderboards = _post_leaderboards

        try:
            self.loop.run_until_complete(bot.start(initial_settings["token"]))
        except Exception as e:
            self.last_error = str(e)
        finally:
            self.bot_user = None
            self.bot = None
            self._post_schedule = None
            self._post_leaderboards = None


mgr = BotManager()

# ── Flask routes ─────────────────────────────────────────────────────────────

@flask_app.before_request
def require_login():
    if request.path.startswith("/static") or request.path in ("/login", "/signup", "/add", "/logout"):
        return
    if request.path.startswith("/verify/") or request.path.startswith("/unlink/"):
        return
    if not session.get("logged_in"):
        return redirect("/login")
    # Scrim hosts can only access the dashboard and its scrim APIs
    if session.get("role") == "host":
        HOST_ALLOWED_PATHS = {
            "/", "/api/me", "/api/meta", "/api/status",
            "/api/signups", "/api/signups/missed", "/api/channels",
            "/api/scrim/start", "/api/scrim/conclude", "/api/scrim/dispatch",
            "/api/scrim/end-dispatch", "/api/scrim/started",
            "/api/code-alert", "/logout",
        }
        if request.path not in HOST_ALLOWED_PATHS:
            return jsonify({"error": "Forbidden"}), 403

@flask_app.route("/api/me")
def api_me():
    s = load_settings()
    return jsonify({"role": session.get("role", "admin"), "username": s.get("account_username", LOGIN_USERNAME or "")})


@flask_app.route("/api/account/update", methods=["POST"])
def api_account_update():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    body = request.json or {}
    u = body.get("username", "").strip()
    p = body.get("password", "")
    p2 = body.get("confirm_password", "")
    if not u or len(u) < 3:
        return jsonify({"error": "Username must be at least 3 characters"}), 400
    if p and len(p) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    if p and p != p2:
        return jsonify({"error": "Passwords do not match"}), 400
    s = load_settings()
    s["account_username"] = u
    if p:
        s["account_password_hash"] = generate_password_hash(p)
    save_settings(s)
    return jsonify({"ok": True})

@flask_app.route("/api/host-password", methods=["POST"])
def api_set_host_password():
    password = str((request.json or {}).get("password", "")).strip()
    s = load_settings()
    if not password:
        s.pop("scrim_host_password_hash", None)
        save_settings(s)
        return jsonify({"ok": True, "cleared": True})
    s["scrim_host_password_hash"] = generate_password_hash(password)
    save_settings(s)
    return jsonify({"ok": True})

@flask_app.route("/login", methods=["GET", "POST"])
def login():
    if not _account_exists():
        return redirect("/signup")
    error = None
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        role = _check_login(u, p)
        if role:
            session["logged_in"] = True
            session["role"] = role
            return redirect("/")
        error = "Wrong username or password"
    s = load_settings()
    can_signup = not bool(s.get("account_password_hash"))
    return render_template("login.html", error=error, can_signup=can_signup)


@flask_app.route("/signup", methods=["GET", "POST"])
def signup():
    error = None
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        p2 = request.form.get("confirm_password", "")
        if not u:
            error = "Username is required"
        elif len(u) < 3:
            error = "Username must be at least 3 characters"
        elif not p:
            error = "Password is required"
        elif len(p) < 6:
            error = "Password must be at least 6 characters"
        elif p != p2:
            error = "Passwords do not match"
        else:
            s = load_settings()
            s["account_username"] = u
            s["account_password_hash"] = generate_password_hash(p)
            save_settings(s)
            session["logged_in"] = True
            session["role"] = "admin"
            return redirect("/")
    is_update = session.get("logged_in", False)
    return render_template("signup.html", error=error, is_update=is_update)

@flask_app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect("/login")

@flask_app.after_request
def no_cache(r):
    r.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    r.headers["Pragma"] = "no-cache"
    return r

@flask_app.route("/")
def index():
    flask_app.jinja_env.cache = {}
    return render_template("index.html")

@flask_app.route("/static/<path:filename>")
def static_files(filename):
    from flask import send_from_directory
    return send_from_directory(os.path.join(BASE_DIR, "static"), filename)

@flask_app.route("/api/meta")
def api_meta():
    return jsonify({"scrims": {k: {"name": v["name"], "emoji": v["emoji"], "hex": v["hex"], "party": v["party"]} for k, v in SCRIMS.items()}})

@flask_app.route("/add")
def add_page():
    if not mgr.is_running() or not mgr.bot or not mgr.bot.user:
        return render_template("add_bot.html", invite_url="", bot_name="Ocean Scrims Helper", bot_avatar="")
    client_id  = mgr.bot.user.id
    invite_url = f"https://discord.com/oauth2/authorize?client_id={client_id}&permissions=8&scope=bot"
    avatar_url = mgr.bot.user.display_avatar.url if mgr.bot.user.display_avatar else ""
    return render_template("add_bot.html", invite_url=invite_url,
                           bot_name=str(mgr.bot.user.name), bot_avatar=avatar_url)


@flask_app.route("/api/bot/invite-url")
def api_bot_invite_url():
    if not mgr.is_running() or not mgr.bot or not mgr.bot.user:
        return jsonify({"error": "Bot must be running to generate an invite URL"}), 400
    client_id = mgr.bot.user.id
    # permissions=8 = Administrator
    url = f"https://discord.com/oauth2/authorize?client_id={client_id}&permissions=8&scope=bot"
    return jsonify({"url": url, "client_id": str(client_id)})


@flask_app.route("/api/status")
def api_status():
    s = load_settings()
    return jsonify({
        "running": mgr.is_running(),
        "user": mgr.bot_user or "",
        "error": mgr.last_error or "",
        "active_scrim": s.get("active_scrim"),
        "active_scrim_started": s.get("active_scrim_started"),
        "scrim_channel_id": s.get("scrim_channel_id"),
        "signup_count": len(s.get("signups", [])),
        "missed_count": len(s.get("missed_signups", [])),
        "dispatched": s.get("dispatched", False),
        "game_number": s.get("game_number", 0),
        "max_games": s.get("max_games", 0),
        "schedule_enabled": s.get("schedule_enabled", False),
        "next_game_ts": _next_interval_ts(
            int(s.get("schedule_interval", 30)),
            s.get("schedule_start_time", "00:00")
        ),
    })

@flask_app.route("/api/signups")
def api_signups():
    s = load_settings()
    return jsonify({"signups": s.get("signups", []), "active_scrim": s.get("active_scrim")})

@flask_app.route("/api/bot/start", methods=["POST"])
def api_bot_start():
    s = load_settings()
    if not s.get("token"):
        return jsonify({"error": "No bot token — go to Config tab first"}), 400
    mgr.start(s)
    return jsonify({"ok": True})

@flask_app.route("/api/bot/stop", methods=["POST"])
def api_bot_stop():
    mgr.stop()
    return jsonify({"ok": True})

@flask_app.route("/api/roles")
def api_roles():
    s = load_settings()
    gid = s.get("guild_id")
    if not gid or not mgr.is_running() or not mgr.bot:
        return jsonify({"roles": []})
    async def _fetch():
        guild = mgr.bot.get_guild(int(gid))
        if not guild:
            return []
        return [{"id": str(r.id), "name": r.name}
                for r in reversed(guild.roles) if r.name != "@everyone"]
    try:
        roles = asyncio.run_coroutine_threadsafe(_fetch(), mgr.loop).result(timeout=5)
        return jsonify({"roles": roles})
    except Exception:
        return jsonify({"roles": []})


@flask_app.route("/api/channels")
def api_channels():
    s = load_settings()
    gid = s.get("guild_id")
    if not gid or not mgr.is_running():
        return jsonify({"channels": []})
    return jsonify({"channels": mgr.get_channels(gid)})

@flask_app.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify(load_settings())

@flask_app.route("/api/settings", methods=["POST"])
def api_save_settings():
    body = request.json or {}
    s = load_settings()
    for key in ["token", "guild_id", "scrim_channel_id", "invite_link",
                "command_prefix", "host_name", "platforms", "verification_required",
                "schedule_enabled", "schedule_channel_id", "schedule_scrim_type",
                "schedule_interval", "schedule_start_time", "schedule_links",
                "commands", "start_messages",
                "concluded_line1", "concluded_line2", "concluded_line3",
                "verify_channel_id", "base_url", "epic_client_id", "epic_client_secret",
                "scrim_priority_roles",
                "dispatch_title_prefix", "dispatch_title_suffix",
                "dispatch_intro", "dispatch_missed", "dispatch_signed"]:
        if key in body:
            s[key] = body[key]
    save_settings(s)
    return jsonify({"ok": True})

@flask_app.route("/api/scrim/start", methods=["POST"])
def api_scrim_start():
    body = request.json or {}
    key = body.get("key")
    if key not in SCRIMS:
        return jsonify({"error": "Unknown scrim type"}), 400
    s = load_settings()
    if not s.get("scrim_channel_id"):
        return jsonify({"error": "No scrim channel set — pick one in Dashboard"}), 400
    if not mgr.is_running():
        return jsonify({"error": "Bot is not running"}), 400
    s["active_scrim"] = key
    s["active_scrim_started"] = datetime.utcnow().isoformat()
    s["signups"] = []
    s["missed_signups"] = []
    s["active_scrim_message_id"] = None
    s["active_dispatch_message_id"] = None
    s["dispatched"] = False
    save_settings(s)
    snap = dict(s)

    async def do():
        ch = mgr.bot.get_channel(int(snap["scrim_channel_id"]))
        if not ch:
            return
        scrim = SCRIMS[key]
        loading = discord.Embed(color=scrim["color"])
        loading.description = "⠋  **Opening custom match...**"
        loading.set_footer(text="\U0001f30a Ocean Scrims")
        msg = await ch.send("@everyone", embed=loading)
        for spinner, label in [
            ("⠙", "Setting up lobbies..."),
            ("⠹", "Preparing scrim..."),
            ("⠸", "Sign-ups opening soon..."),
            ("✅", "**Sign-ups are OPEN!**"),
        ]:
            await asyncio.sleep(0.65)
            frame = discord.Embed(color=scrim["color"])
            frame.description = f"{spinner}  **{label}**"
            frame.set_footer(text="\U0001f30a Ocean Scrims")
            await msg.edit(embed=frame)
        await asyncio.sleep(0.4)
        embed = build_signup_embed(key, snap, ch.guild)
        await msg.edit(embed=embed)
        await msg.add_reaction("✋")
        s2 = load_settings()
        s2["active_scrim_message_id"] = str(msg.id)
        save_settings(s2)

    mgr.fire(do())
    return jsonify({"ok": True})

@flask_app.route("/api/scrim/conclude", methods=["POST"])
def api_scrim_conclude():
    s = load_settings()
    active = s.get("active_scrim")
    ch_id = s.get("scrim_channel_id")
    if not active or active not in SCRIMS:
        return jsonify({"error": "No active scrim"}), 400
    if not ch_id:
        return jsonify({"error": "No scrim channel configured"}), 400
    if not mgr.is_running():
        return jsonify({"error": "Bot is not running"}), 400
    snap = dict(s)

    async def do():
        ch = mgr.bot.get_channel(int(ch_id))
        if ch:
            await send_concluded_embed(ch, active, snap)

    mgr.fire(do())
    s["active_scrim"] = None
    s["active_scrim_started"] = None
    s["active_scrim_message_id"] = None
    save_settings(s)
    return jsonify({"ok": True})

@flask_app.route("/api/scrim/dispatch", methods=["POST"])
def api_scrim_dispatch():
    body = request.json or {}
    match_code = str(body.get("match_code", "")).strip()
    if not match_code:
        return jsonify({"error": "Match code is required"}), 400
    s = load_settings()
    active = s.get("active_scrim")
    ch_id = s.get("scrim_channel_id")
    if not active or active not in SCRIMS:
        return jsonify({"error": "No active scrim"}), 400
    if not ch_id:
        return jsonify({"error": "No scrim channel configured"}), 400
    if not mgr.is_running():
        return jsonify({"error": "Bot is not running"}), 400

    orig_msg_id = s.get("active_scrim_message_id")
    snap = dict(s)

    async def do():
        ch = mgr.bot.get_channel(int(ch_id))
        if not ch:
            return

        # Delete the original sign-up message
        if orig_msg_id:
            try:
                orig = await ch.fetch_message(int(orig_msg_id))
                await orig.delete()
            except Exception:
                pass

        scrim = SCRIMS[active]

        # Siren alert animation: dark → urgent red → scrim colour
        ramp_frames = [
            (0x1A0000, "🚨  **INCOMING DISPATCH — Stand by...**"),
            (0x2D0500, "🔐  **Locking in match code...**"),
            (0x1A0020, "📡  **Broadcasting to all players...**"),
            (0x002530, "⚡  **Code confirmed — launching now...**"),
            (scrim["color"], f"🚀  **{scrim['emoji']} DISPATCHED!**"),
        ]

        init = discord.Embed(color=ramp_frames[0][0])
        init.description = ramp_frames[0][1]
        init.set_footer(text="\U0001f30a Ocean Scrims")
        msg = await ch.send("@everyone", embed=init)

        for color, desc in ramp_frames[1:]:
            await asyncio.sleep(0.62)
            frame = discord.Embed(color=color)
            frame.description = desc
            frame.set_footer(text="\U0001f30a Ocean Scrims")
            await msg.edit(embed=frame)

        await asyncio.sleep(0.5)

        # Dispatch embed
        host         = snap.get("host_name") or "Ocean Scrims"
        game_num     = snap.get("game_number") or 1
        signup_count = len(snap.get("signups", []))
        d_prefix = snap.get("dispatch_title_prefix", "🚨").strip()
        d_suffix = snap.get("dispatch_title_suffix", "🚨").strip()
        d_intro  = snap.get("dispatch_intro",  "**The lobby is live — get in!**")
        d_missed = snap.get("dispatch_missed", "🟥  **Missed queue?** — React ✋ below to sign up late")
        d_signed = snap.get("dispatch_signed", "⭕  **Already signed up?** — Ignore this message")

        title_parts = [p for p in [d_prefix, f"{scrim['emoji']}  {scrim['name'].upper()} DISPATCH", d_suffix] if p]
        embed = discord.Embed(
            title="  ".join(title_parts),
            color=scrim["color"],
        )
        embed.description = f"{d_intro}\n\n{d_missed}\n{d_signed}\n"
        embed.add_field(name="🔑  Match Code", value=f"```\n{match_code}\n```", inline=False)
        embed.set_footer(text=f"\U0001f30a {host}  •  Game #{game_num}  •  {signup_count} players")
        await msg.edit(embed=embed)
        await msg.add_reaction("✋")

        s2 = load_settings()
        s2["active_dispatch_message_id"] = str(msg.id)
        s2["active_scrim_message_id"] = None
        s2["missed_signups"] = []
        s2["dispatched"] = True
        save_settings(s2)

    mgr.fire(do())
    s["dispatched"] = True
    save_settings(s)
    return jsonify({"ok": True})


@flask_app.route("/api/scrim/end-dispatch", methods=["POST"])
def api_scrim_end_dispatch():
    s = load_settings()
    dispatch_msg_id = s.get("active_dispatch_message_id")
    dispatch_ch_id = s.get("scrim_channel_id")
    if not mgr.is_running():
        return jsonify({"error": "Bot is not running"}), 400

    async def do():
        if dispatch_msg_id and dispatch_ch_id:
            try:
                ch = mgr.bot.get_channel(int(dispatch_ch_id))
                if ch:
                    msg = await ch.fetch_message(int(dispatch_msg_id))
                    await msg.delete()
            except Exception:
                pass

    mgr.fire(do())
    s["dispatched"] = False
    s["active_dispatch_message_id"] = None
    save_settings(s)
    return jsonify({"ok": True})


@flask_app.route("/api/signups/missed")
def api_missed_signups():
    s = load_settings()
    return jsonify({"missed_signups": s.get("missed_signups", [])})


@flask_app.route("/api/scrim/started", methods=["POST"])
def api_scrim_started():
    body = request.json or {}
    try:
        count = int(body.get("count", 0))
    except (ValueError, TypeError):
        count = 0
    next_game_time = str(body.get("next_game_time", "")).strip() or None
    s = load_settings()
    if not mgr.is_running():
        return jsonify({"error": "Bot is not running"}), 400
    fn = getattr(mgr, "_post_started", None)
    if not fn:
        return jsonify({"error": "Bot not fully ready yet"}), 400
    ch_id = s.get("schedule_channel_id") or s.get("scrim_channel_id")
    if not ch_id:
        return jsonify({"error": "No channel configured"}), 400
    mgr.fire(fn(None, s, count, next_game_time=next_game_time))
    return jsonify({"ok": True})


@flask_app.route("/api/code-alert", methods=["POST"])
def api_code_alert():
    body = request.json or {}
    channel_id = str(body.get("channel_id", "")).strip()
    minutes = body.get("minutes")
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid minutes value"}), 400
    if not channel_id:
        return jsonify({"error": "No channel selected"}), 400
    if not mgr.is_running():
        return jsonify({"error": "Bot is not running"}), 400
    label = "MINUTE" if minutes == 1 else "MINUTES"
    message = f"CODE IN {minutes} {label}\n\n@everyone"

    async def do():
        ch = mgr.bot.get_channel(int(channel_id))
        if ch:
            await ch.send(message)

    mgr.fire(do())
    return jsonify({"ok": True})


@flask_app.route("/api/schedule/post", methods=["POST"])
def api_schedule_post():
    s = load_settings()
    if not s.get("schedule_channel_id"):
        return jsonify({"error": "No schedule channel configured"}), 400
    if not mgr.is_running():
        return jsonify({"error": "Bot is not running"}), 400
    fn = getattr(mgr, "_post_schedule", None)
    if not fn:
        return jsonify({"error": "Bot not fully ready yet"}), 400
    body = request.json or {}
    scrim_key = body.get("scrim_key") or None
    mgr.fire(fn(s, override_scrim_key=scrim_key))
    return jsonify({"ok": True})


@flask_app.route("/api/post-invite", methods=["POST"])
def api_post_invite():
    body = request.json or {}
    channel_id = str(body.get("channel_id", "")).strip()
    if not channel_id:
        return jsonify({"error": "No channel selected"}), 400
    if not mgr.is_running():
        return jsonify({"error": "Bot is not running"}), 400
    s = load_settings()
    if not s.get("invite_link"):
        return jsonify({"error": "No invite link set — add one in Settings"}), 400
    fn = getattr(mgr, "_post_invite", None)
    if not fn:
        return jsonify({"error": "Bot not fully ready"}), 400

    async def do():
        ch = mgr.bot.get_channel(int(channel_id))
        if ch:
            await fn(ch, s)

    mgr.fire(do())
    return jsonify({"ok": True})


@flask_app.route("/api/leaderboard/post", methods=["POST"])
def api_leaderboard_post():
    body = request.json or {}
    channel_id = str(body.get("channel_id", "")).strip()
    scrim_key = body.get("scrim_key") or None
    if not channel_id:
        return jsonify({"error": "No channel selected"}), 400
    if not mgr.is_running():
        return jsonify({"error": "Bot is not running"}), 400
    fn = getattr(mgr, "_post_leaderboards", None)
    if not fn:
        return jsonify({"error": "Bot not fully ready yet"}), 400
    s = load_settings()

    async def do():
        ch = mgr.bot.get_channel(int(channel_id))
        if ch:
            await fn(ch, s, scrim_key)

    mgr.fire(do())
    return jsonify({"ok": True})


@flask_app.route("/api/scrim/announce", methods=["POST"])
def api_scrim_announce():
    body = request.json or {}
    channel_id = str(body.get("channel_id", "")).strip()
    scrim_key  = str(body.get("scrim_key", "solos")).strip()
    title      = str(body.get("title", "")).strip()
    start_time = str(body.get("start_time", "")).strip()
    message    = str(body.get("message", "")).strip()
    ping       = bool(body.get("ping_everyone", True))

    if not channel_id:
        return jsonify({"error": "No channel selected"}), 400
    if scrim_key not in SCRIMS:
        return jsonify({"error": "Invalid scrim type"}), 400
    if not start_time:
        return jsonify({"error": "Start time is required"}), 400
    if not mgr.is_running():
        return jsonify({"error": "Bot is not running"}), 400

    ts = _time_str_to_ts(start_time)
    if not ts:
        return jsonify({"error": "Invalid time"}), 400

    scrim = SCRIMS[scrim_key]
    auto_title = title or f"{scrim['name'].upper()} SCRIMS"

    async def do():
        ch = mgr.bot.get_channel(int(channel_id))
        if not ch:
            return

        lines = [
            f"**__{auto_title}__**",
            f"> Games will begin Today at <t:{ts}:T>  ~  <t:{ts}:R>",
            f'> React with " ✋ " if you will participate in the scrims.',
        ]
        if message:
            lines.append(f"> • {message}")
        if ping:
            lines.append("@everyone")

        msg = await ch.send("\n".join(lines))
        await msg.add_reaction("✋")

    mgr.fire(do())
    return jsonify({"ok": True})


@flask_app.route("/verify/complete/<token>")
def verify_complete(token):
    """Landing page Epic redirects to after the user signs in."""
    info = PENDING_VERIFICATIONS.get(token)
    if not info:
        return render_template("verify_result.html", success=False,
                               message="This verification link has expired or already been used.")
    return render_template("verify_page.html",
        fin_token=token,
        username=info["username"],
        epic_name="",
        guild_name=info["guild_name"],
        guild_icon=info.get("guild_icon", ""),
    )


@flask_app.route("/verify/epic/finalize/<fin_token>", methods=["POST"])
def verify_finalize(fin_token):
    """Called by JS after the countdown completes."""
    body      = request.get_json(silent=True) or {}
    epic_name = str(body.get("epic_name", "")).strip()

    info = PENDING_VERIFICATIONS.pop(f"fin_{fin_token}", None) or PENDING_VERIFICATIONS.pop(fin_token, None)
    if not info:
        return jsonify({"error": "expired"}), 404
    PENDING_VERIFICATIONS.pop(info.get("state", ""), None)

    # Prefer the name sent by the page over anything stored in the token
    if not epic_name:
        epic_name = info.get("epic_name", "")

    s        = load_settings()
    verified = s.get("verified_users", [])
    user_id  = info["user_id"]
    now      = datetime.utcnow().isoformat()
    entry    = next((v for v in verified if v["user_id"] == user_id), None)
    if entry:
        entry.update({"epic_name": epic_name, "timestamp": now})
    else:
        verified.append({"user_id": user_id, "username": info["username"],
                         "epic_name": epic_name, "timestamp": now})
    s["verified_users"] = verified
    save_settings(s)

    unlink_tok = secrets.token_urlsafe(20)
    base_url   = s.get("base_url", f"http://localhost:{PORT}").rstrip("/")
    PENDING_VERIFICATIONS[f"unlink_{unlink_tok}"] = {"user_id": user_id, "username": info["username"]}
    unlink_url = f"{base_url}/unlink/{unlink_tok}"

    uid        = user_id
    uname      = info["username"]
    guild_name = info.get("guild_name", "Ocean Scrims")
    guild_icon = info.get("guild_icon")
    guild_id   = s.get("guild_id", "")

    async def _finish():
        try:
            user = await mgr.bot.fetch_user(int(uid))

            # Verified confirmation embed
            embed = discord.Embed(color=0x00FF94)
            embed.set_author(name=f"{guild_name}  •  Verified", icon_url=guild_icon)
            embed.title = "✅  Account Verified!"
            embed.description = (
                f"You are now verified on **{guild_name}**.\n"
                f"You now have full access to scrim lobbies. Welcome! 🌊\n\n"
                f"**Reply to this message with your Fortnite username** and the bot will set your server nickname automatically."
            )
            embed.add_field(name="Discord", value=f"**{uname}**",      inline=True)
            embed.add_field(name="Access",  value="🎮  Scrim Lobbies", inline=True)
            if guild_icon:
                embed.set_thumbnail(url=guild_icon)
            embed.set_footer(text="🌊 Ocean Scrims  •  Click below to unlink")
            embed.timestamp = datetime.utcnow()
            msg = await user.send(embed=embed, view=_URLView("Unlink Account", unlink_url, "🔓"))

            # Mark user as waiting for a nickname reply
            if guild_id:
                PENDING_NICKNAME[uid] = {"guild_id": guild_id, "dm_channel_id": str(msg.channel.id)}
        except Exception:
            pass

    if mgr.is_running():
        mgr.fire(_finish())

    return jsonify({"ok": True, "epic_name": epic_name})


@flask_app.route("/verify/epic/callback")
def verify_epic_callback():
    error = request.args.get("error", "")
    if error:
        return render_template("verify_result.html", success=False,
                               message="Epic login was cancelled or denied.")

    code  = request.args.get("code", "")
    state = request.args.get("state", "")
    info  = PENDING_VERIFICATIONS.get(state)
    if not info:
        return render_template("verify_result.html", success=False,
                               message="This verification link has expired or already been used.")

    s             = load_settings()
    client_id     = s.get("epic_client_id", "").strip()
    client_secret = s.get("epic_client_secret", "").strip()
    base_url      = s.get("base_url", f"http://localhost:{PORT}").rstrip("/")
    redirect_uri  = f"{base_url}/verify/epic/callback"

    try:
        # Exchange code → access token
        body  = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}).encode()
        creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        req   = urllib.request.Request(EPIC_TOKEN_URL, data=body,
                    headers={"Authorization": f"Basic {creds}",
                             "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=10) as r:
            token_data = json.loads(r.read())
        access_token = token_data["access_token"]

        # Fetch Epic user info
        uinfo = urllib.request.Request(EPIC_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"})
        with urllib.request.urlopen(uinfo, timeout=10) as r:
            epic_user = json.loads(r.read())

        epic_name = epic_user.get("preferred_username") or epic_user.get("name") or "Unknown"
        epic_id   = epic_user.get("sub", "")
    except Exception:
        return render_template("verify_result.html", success=False,
                               message="Could not connect to Epic Games. Please try again.")

    # Store finalize data; the countdown page calls back to complete recording
    fin_token = secrets.token_urlsafe(20)
    PENDING_VERIFICATIONS[f"fin_{fin_token}"] = {**info, "epic_name": epic_name, "epic_id": epic_id, "state": state}

    return render_template("verify_page.html",
        fin_token=fin_token,
        username=info["username"],
        epic_name=epic_name,
        guild_name=info["guild_name"],
        guild_icon=info.get("guild_icon", ""),
    )


@flask_app.route("/unlink/<token>")
def unlink_page(token):
    info = PENDING_VERIFICATIONS.get(f"unlink_{token}")
    if not info:
        return render_template("verify_result.html", success=False,
                               message="This unlink link is invalid or has already been used.")
    return render_template("unlink_page.html", token=token, username=info["username"])


@flask_app.route("/unlink/<token>/confirm", methods=["POST"])
def unlink_confirm(token):
    info = PENDING_VERIFICATIONS.pop(f"unlink_{token}", None)
    if not info:
        return jsonify({"error": "expired"}), 404
    s = load_settings()
    s["verified_users"] = [v for v in s.get("verified_users", []) if v["user_id"] != info["user_id"]]
    save_settings(s)
    return jsonify({"ok": True})


@flask_app.route("/api/verify/users")
def api_verify_users():
    s = load_settings()
    return jsonify({"verified_users": s.get("verified_users", [])})


@flask_app.route("/api/verify/remove", methods=["POST"])
def api_verify_remove():
    user_id = str((request.json or {}).get("user_id", ""))
    s = load_settings()
    s["verified_users"] = [v for v in s.get("verified_users", []) if v["user_id"] != user_id]
    save_settings(s)
    return jsonify({"ok": True})


@flask_app.route("/api/verify/post", methods=["POST"])
def api_verify_post():
    s = load_settings()
    ch_id = s.get("verify_channel_id")
    if not ch_id:
        return jsonify({"error": "No verify channel configured"}), 400
    if not mgr.is_running():
        return jsonify({"error": "Bot is not running"}), 400

    async def do():
        ch = mgr.bot.get_channel(int(ch_id))
        if not ch:
            return
        embed = discord.Embed(
            title="Epic Account Verification",
            description=(
                "Please click on the raised hand below to link your Epic Account. "
                "You will receive a direct message from the bot with further instructions."
            ),
            color=0x00B4D8,
        )
        if ch.guild.icon:
            embed.set_thumbnail(url=ch.guild.icon.url)
        embed.set_footer(text="\U0001f30a Ocean Scrims")
        await ch.send(embed=embed, view=VerifyView())

    mgr.fire(do())
    return jsonify({"ok": True})


def setup_host():
    import sys
    if sys.platform != "win32":
        return
    hosts = r"C:\Windows\System32\drivers\etc\hosts"
    try:
        with open(hosts, "r") as f:
            content = f.read()
        if "oceanbot" not in content:
            with open(hosts, "a") as f:
                f.write("\n127.0.0.1\toceanbot\n")
        print("Custom URL ready: http://oceanbot:3000/")
    except PermissionError:
        print("NOTE: Run as Administrator once to enable http://oceanbot:3000/")
        print("      Using http://localhost:3000/ for now")
    except Exception:
        pass


if __name__ == "__main__":
    setup_host()
    s = load_settings()
    if s.get("token"):
        mgr.start(s)
    print(f"Ocean Bot -> http://localhost:{PORT}/")
    def _open_browser():
        import time, webbrowser
        time.sleep(2.5)
        webbrowser.open(f"http://localhost:{PORT}")
    threading.Thread(target=_open_browser, daemon=True).start()
    flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
