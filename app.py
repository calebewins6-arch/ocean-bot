from flask import Flask, render_template, request, jsonify, session, redirect
import discord
from discord.ext import commands
import json, os, threading, asyncio, logging, secrets
from datetime import datetime, timedelta

logging.getLogger("werkzeug").setLevel(logging.ERROR)

# Railway / cloud sets PORT and DISCORD_TOKEN as environment variables
PORT = int(os.environ.get("PORT", 3000))
ENV_TOKEN = os.environ.get("DISCORD_TOKEN", "")

flask_app = Flask(__name__)
flask_app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

LOGIN_USERNAME = os.environ.get("LOGIN_USERNAME", "cabz2x")
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


def build_signup_embed(scrim_key, settings, guild=None):
    scrim = SCRIMS[scrim_key]
    embed = discord.Embed(title="Tournament Matchmaking", color=scrim["color"])
    embed.description = (
        "A new custom match has been opened!\n"
        "**Please click ✋ to sign up for the scrim.**\n\n"
        "Make sure to have the correct amount of players in your party."
    )
    embed.add_field(name="Game Mode", value=f"{scrim['emoji']} {scrim['name']} Scrims", inline=True)
    embed.add_field(name="Players in your party", value=str(scrim["party"]), inline=True)
    if settings.get("verification_required", True):
        embed.add_field(name="⚠️  Verification required  ⚠️",
                        value="All members of your team must be verified on this server.", inline=False)
    embed.add_field(name="Allowed Platforms", value=settings.get("platforms", "PC / Windows, PlayStation, Xbox, Mobile"), inline=False)
    embed.add_field(name="Host", value=settings.get("host_name", "Ocean Scrims"), inline=False)
    if guild and guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.set_footer(text="\U0001f30a Ocean Scrims")
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
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        intents = discord.Intents.all()
        bot = commands.Bot(command_prefix=initial_settings.get("command_prefix", "!"), intents=intents)
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
        @bot.event
        async def on_ready():
            self.bot_user = str(bot.user)
            print(f"Bot online: {bot.user}")
            bot.loop.create_task(schedule_loop())

        @bot.event
        async def on_message(message):
            if message.author.bot:
                return
            s = load_settings()
            prefix = s.get("command_prefix", "!")
            if not message.content.startswith(prefix):
                return
            raw = message.content[len(prefix):].strip()
            cmd = raw.lower().split()[0] if raw.split() else ""
            cmds = s.get("commands", {})
            for scrim_key in SCRIMS:
                if cmd == cmds.get(scrim_key, "").lower():
                    await _start_scrim(message.channel, s, scrim_key)
                    return
            if cmd == cmds.get("concluded", "concluded").lower():
                await _conclude(message.channel, s)
                return
            if cmd == cmds.get("started", "started").lower():
                parts = raw.split()
                count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                # Optional: !started 100 18:30
                next_game_time = parts[2] if len(parts) > 2 and ":" in parts[2] else None
                await _post_started(message.channel, s, count, next_game_time=next_game_time)
                return
            if cmd == cmds.get("invite", "invite").lower():
                await _post_invite(message.channel, s)
                return

        async def _post_started(source_channel, s, player_count, next_game_time=None):
            ch_id = s.get("schedule_channel_id") or s.get("scrim_channel_id")
            ch = (bot.get_channel(int(ch_id)) if ch_id else None) or source_channel
            if not ch:
                return

            # Increment game counter
            s2 = load_settings()
            s2["game_number"] = s2.get("game_number", 0) + 1
            game_num = s2["game_number"]
            max_games = int(s2.get("max_games", 0))
            save_settings(s2)

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
            save_settings(s3)

            # Auto-conclude when max games reached
            if max_games > 0 and game_num >= max_games:
                s3 = load_settings()
                if s3.get("active_scrim") and s3.get("scrim_channel_id"):
                    conclude_ch = bot.get_channel(int(s3["scrim_channel_id"]))
                    if conclude_ch:
                        await send_concluded_embed(conclude_ch, s3["active_scrim"], s3)
                s3["active_scrim"] = None
                s3["active_scrim_started"] = None
                s3["active_scrim_message_id"] = None
                s3["game_number"] = 0
                save_settings(s3)

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
        async def on_raw_reaction_add(payload):
            if payload.user_id == bot.user.id:
                return
            s = load_settings()
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
                        save_settings(s)

            # 🙋 missed-out on the dispatch message
            elif str(payload.message_id) == str(s.get("active_dispatch_message_id")):
                if str(payload.emoji) == "🙋":
                    missed = s.get("missed_signups", [])
                    if not any(m["user_id"] == str(payload.user_id) for m in missed):
                        missed.append({
                            "user_id": str(payload.user_id),
                            "username": uname,
                            "timestamp": datetime.utcnow().isoformat(),
                        })
                        s["missed_signups"] = missed
                        save_settings(s)

        @bot.event
        async def on_raw_reaction_remove(payload):
            s = load_settings()
            emoji = str(payload.emoji)

            if emoji == "✋" and str(payload.message_id) == str(s.get("active_scrim_message_id")):
                s["signups"] = [su for su in s.get("signups", []) if su["user_id"] != str(payload.user_id)]
                save_settings(s)

            elif emoji == "🙋" and str(payload.message_id) == str(s.get("active_dispatch_message_id")):
                s["missed_signups"] = [m for m in s.get("missed_signups", []) if m["user_id"] != str(payload.user_id)]
                save_settings(s)

        async def _start_scrim(channel, s, scrim_key):
            ch_id = s.get("scrim_channel_id")
            target = (bot.get_channel(int(ch_id)) if ch_id else None) or channel
            s["active_scrim"] = scrim_key
            s["active_scrim_started"] = datetime.utcnow().isoformat()
            s["signups"] = []
            s["active_scrim_message_id"] = None
            save_settings(s)
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
            save_settings(s)

        async def _conclude(channel, s):
            active = s.get("active_scrim")
            ch_id = s.get("scrim_channel_id")
            target = (bot.get_channel(int(ch_id)) if ch_id else None) or channel
            if not active or active not in SCRIMS:
                await channel.send("No active scrim to conclude.", delete_after=5)
                return
            await send_concluded_embed(target, active, s)
            s["active_scrim"] = None
            s["active_scrim_started"] = None
            s["active_scrim_message_id"] = None
            s["game_number"] = 0
            s["dispatched"] = False
            save_settings(s)

        # Store _post_schedule so Flask can call it
        self._post_schedule = _post_schedule

        try:
            self.loop.run_until_complete(bot.start(initial_settings["token"]))
        except Exception as e:
            self.last_error = str(e)
        finally:
            self.bot_user = None
            self.bot = None
            self._post_schedule = None


mgr = BotManager()

# ── Flask routes ─────────────────────────────────────────────────────────────

@flask_app.before_request
def require_login():
    if request.path.startswith("/static") or request.path == "/login":
        return
    if not session.get("logged_in"):
        return redirect("/login")

@flask_app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        if u == LOGIN_USERNAME and p == LOGIN_PASSWORD and LOGIN_PASSWORD:
            session["logged_in"] = True
            return redirect("/")
        error = "Wrong username or password"
    return render_template("login.html", error=error)

@flask_app.route("/logout", methods=["POST"])
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
    return render_template("index.html")

@flask_app.route("/static/<path:filename>")
def static_files(filename):
    from flask import send_from_directory
    return send_from_directory(os.path.join(BASE_DIR, "static"), filename)

@flask_app.route("/api/meta")
def api_meta():
    return jsonify({"scrims": {k: {"name": v["name"], "emoji": v["emoji"], "hex": v["hex"], "party": v["party"]} for k, v in SCRIMS.items()}})

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
                "concluded_line1", "concluded_line2", "concluded_line3"]:
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

        # Colour-ramp animation: near-black → scrim colour on final frame
        ramp_colors = [0x06080A, 0x0A1018, 0x0D1A28, 0x102238]
        ramp_frames = [
            (ramp_colors[0], "🔐  **Securing match...**"),
            (ramp_colors[1], "📡  **Broadcasting lobby...**"),
            (ramp_colors[2], "🔓  **Code locked in...**"),
            (ramp_colors[3], "⚡  **Launching dispatch...**"),
            (scrim["color"],  "🚀  **DISPATCHED!**"),
        ]

        init = discord.Embed(color=ramp_frames[0][0])
        init.description = ramp_frames[0][1]
        init.set_footer(text="\U0001f30a Ocean Scrims")
        msg = await ch.send("@everyone", embed=init)

        for color, desc in ramp_frames[1:]:
            await asyncio.sleep(0.7)
            frame = discord.Embed(color=color)
            frame.description = desc
            frame.set_footer(text="\U0001f30a Ocean Scrims")
            await msg.edit(embed=frame)

        await asyncio.sleep(0.5)

        # Rich dispatch embed
        embed = discord.Embed(color=scrim["color"])
        embed.title = f"🚀  MATCH DISPATCHED  {scrim['emoji']}"
        embed.description = (
            f"**⚡  CUSTOM MATCH IS NOW LIVE — GET IN LOBBIES!**\n"
            f"> 🙋  React below if you **missed sign-ups**\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔑  **MATCH CODE**\n"
            f"```\n{match_code}\n```"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        embed.add_field(
            name=f"{scrim['emoji']}  Game Mode",
            value=f"**{scrim['name']} Scrims**",
            inline=True,
        )
        embed.add_field(
            name="👥  Party Size",
            value=f"**{scrim['party']} Player{'s' if scrim['party'] != 1 else ''}**",
            inline=True,
        )
        if snap.get("verification_required", True):
            embed.add_field(
                name="⚠️  Verification Required",
                value="All members of your team must be **verified** on this server.",
                inline=False,
            )
        embed.add_field(
            name="🖥️  Platforms",
            value=snap.get("platforms", "PC / Windows, PlayStation, Xbox, Mobile"),
            inline=False,
        )
        embed.add_field(
            name="🎙️  Host",
            value=f"**{snap.get('host_name', 'Ocean Scrims')}**",
            inline=False,
        )
        if ch.guild.icon:
            embed.set_thumbnail(url=ch.guild.icon.url)
        embed.set_footer(text="\U0001f30a Ocean Scrims")
        embed.timestamp = datetime.utcnow()

        if os.path.exists(BANNER_PATH):
            embed.set_image(url="attachment://ocean_banner.png")
            await msg.delete()
            msg = await ch.send(embed=embed, file=discord.File(BANNER_PATH, filename="ocean_banner.png"))
            await msg.add_reaction("🙋")
        else:
            await msg.edit(embed=embed)
            await msg.add_reaction("🙋")

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
