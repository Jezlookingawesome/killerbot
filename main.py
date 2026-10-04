import discord
from discord.ext import commands
from discord import Webhook, app_commands
import aiohttp
import asyncio
from io import BytesIO
import os
import random
import re
import time
import traceback
from urllib.parse import quote
from groq import Groq

TOKEN = os.getenv("TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

murdered_users = {}
roulette_odds = {}
gambling_mode = {}

DEVELOPER_ID = 1478853756874395762
JACKPOT_ROLE_NAME = "JACKPOT☘️"
JACKPOT_ROLE_COLOR = discord.Color.from_rgb(0, 255, 0)

STARLIGHT_EMOJI = "<:starlight:1555998076362162306>"
REVIVE_EMOJI = "<:revive:1555996640769220718>"
TIER_VIAL = "<:starlight_vial:1555996027230888008>"
TIER_BOTTLE = "<:starlight_bottle:1555996085611143361>"
TIER_BARREL = "<:starlight_barrel:1555996132126232806>"
WEBHOOK_NAME = "✦ Starlight"
HELP_COLOR = discord.Color.from_rgb(255, 200, 60)

ARCHITECTS_CHANNEL_NAME = "the-architects"
ARCHITECT_MODEL = "llama-3.3-70b-versatile"
ARCHITECT_MESSAGE_DELAY = 2
ARCHITECT_MAX_EXCHANGES = 20
ARCHITECT_TIMEOUT = 5 * 60

conv_active = {}
conv_started_at = {}
conv_exchanges = {}
conv_last_speaker = {}
conv_last_msg_time = {}
conv_lock = asyncio.Lock()

START_TIME = time.time()

HELP_CATEGORIES = {
    "moderation": {
        "name": "Moderation",
        "commands": [
            ("!murder @user", "kills the user"),
            ("!unmurder @user", "revives them (no mention = revives yourself)"),
            ("!murdered", "lists everyone currently murdered"),
        ],
    },
    "gambling": {
        "name": "Gambling",
        "commands": [
            ("!gamble", "rolls a d20"),
            ("!jgamble", "same as gamble, but if you roll below 10 you DIE"),
            ("!highstakes", "rolls a d1000"),
            ("!shoot @user", "fires at a user — 1/6 chance they die"),
            ("!roulette", "pulls the trigger — the server's odds decide your fate"),
            ("!spin", "randomly sets the server's death odds"),
            ("!loadbullet", "raises the server's odds by 1/6 (max 5/6)"),
            ("!bulletsky", "shoots a bullet into the sky — removes one bullet"),
            ("!emptychamber", "empties the chamber completely (back to 1/6)"),
            ("!checkchamber", "shows how many bullets are loaded"),
        ],
    },
    "creation": {
        "name": "Creation",
        "commands": [
            ("!createchannel <name> <description>", "creates a text channel you manage"),
            ("!createforum <name> <description>", "creates a forum channel you manage"),
            ("!createvc <name>", "creates a voice channel and pulls you into it"),
            ("!enablelinger", "mods only — turns OFF auto-deletion of created channels"),
            ("!disablelinger", "mods only — turns ON auto-deletion of created channels"),
        ],
    },
    "fun": {
        "name": "Fun",
        "commands": [
            ("!cat", "posts a random cat image"),
        ],
    },
    "info": {
        "name": "Info",
        "commands": [
            ("!ping", "shows the bot's latency"),
            ("!stats", "shows bot stats"),
            ("!credits", "shows who made the bot"),
        ],
    },
}

CATEGORY_ORDER = ["all", "moderation", "gambling", "creation", "fun", "info"]
COMMANDS_PER_PAGE = 7


def get_category_commands(category_key):
    if category_key == "all":
        combined = []
        for key in ["moderation", "gambling", "creation", "fun", "info"]:
            combined.extend(HELP_CATEGORIES[key]["commands"])
        return combined
    return HELP_CATEGORIES[category_key]["commands"]


def get_category_label(category_key):
    if category_key == "all":
        return "All Commands"
    return HELP_CATEGORIES[category_key]["name"]


def build_help_embed(category_key: str, page: int):
    commands = get_category_commands(category_key)
    total_pages = max(1, (len(commands) + COMMANDS_PER_PAGE - 1) // COMMANDS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    start = page * COMMANDS_PER_PAGE
    end = start + COMMANDS_PER_PAGE
    chunk = commands[start:end]
    title = f"{STARLIGHT_EMOJI} STARLIGHT — {get_category_label(category_key).upper()}"
    embed = discord.Embed(
        title=title,
        description=f"**Prefix: !**\nPage {page + 1}/{total_pages}",
        color=HELP_COLOR,
    )
    for usage, desc in chunk:
        embed.add_field(name=usage, value=desc, inline=False)
    embed.set_footer(text="Use the arrows to flip pages, or the dropdown to switch categories")
    return embed, total_pages


class CategorySelect(discord.ui.Select):
    def __init__(self, current: str = "all"):
        options = []
        for key in CATEGORY_ORDER:
            label = "All Commands" if key == "all" else HELP_CATEGORIES[key]["name"]
            options.append(
                discord.SelectOption(label=label, value=key, default=(key == current))
            )
        super().__init__(
            placeholder="Categories",
            min_values=1,
            max_values=1,
            options=options,
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        view: HelpView = self.view
        new_category = self.values[0]
        view.category_key = new_category
        view.page = 0
        commands = get_category_commands(new_category)
        view.total_pages = max(1, (len(commands) + COMMANDS_PER_PAGE - 1) // COMMANDS_PER_PAGE)
        view._update_buttons()
        view.remove_item(view.category_select)
        view.category_select = CategorySelect(current=new_category)
        view.add_item(view.category_select)
        embed, _ = build_help_embed(view.category_key, view.page)
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.NotFound:
            await interaction.followup.send("INTERACTION TIMEOUT — RUN `/help` AGAIN.", ephemeral=True)
        except discord.HTTPException:
            pass


class HelpView(discord.ui.View):
    def __init__(self, category_key: str = "all", page: int = 0, author_id: int = None):
        super().__init__(timeout=180)
        self.category_key = category_key
        self.page = page
        self.author_id = author_id
        commands = get_category_commands(category_key)
        self.total_pages = max(1, (len(commands) + COMMANDS_PER_PAGE - 1) // COMMANDS_PER_PAGE)
        self.category_select = CategorySelect(current=category_key)
        self.add_item(self.category_select)
        self._update_buttons()

    def _update_buttons(self):
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.total_pages - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.author_id is not None and interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "FAILED INTERACTION — YOU'RE NOT THE ONE WHO TRIGGERED THE COMMAND.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=0)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        self._update_buttons()
        embed, _ = build_help_embed(self.category_key, self.page)
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.NotFound:
            await interaction.followup.send("INTERACTION TIMEOUT — RUN `/help` AGAIN.", ephemeral=True)
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.total_pages - 1:
            self.page += 1
        self._update_buttons()
        embed, _ = build_help_embed(self.category_key, self.page)
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.NotFound:
            await interaction.followup.send("INTERACTION TIMEOUT — RUN `/help` AGAIN.", ephemeral=True)
        except discord.HTTPException:
            pass


def tier_emoji(member) -> str:
    if member is None:
        return TIER_VIAL
    if member.id == DEVELOPER_ID:
        return TIER_BARREL
    if member.guild and member.guild.owner_id == member.id:
        return TIER_BARREL
    perms = member.guild_permissions
    if perms.administrator:
        return TIER_BARREL
    mod_perms = (
        perms.manage_messages or perms.manage_members or perms.manage_channels
        or perms.manage_roles or perms.manage_webhooks or perms.manage_guild
        or perms.kick_members or perms.ban_members
    )
    if mod_perms:
        return TIER_BOTTLE
    return TIER_VIAL


async def tier_reply(ctx, text):
    emoji = tier_emoji(ctx.author)
    await ctx.reply(f"{text} — {emoji}")


def grey_url(user):
    avatar = str(user.display_avatar.with_size(256).url)
    return f"https://some-random-api.com/canvas/greyscale?avatar={quote(avatar, safe='')}"


async def fetch_grey_image(user):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(grey_url(user)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
        return discord.File(BytesIO(data), filename="grey.png")
    except Exception as e:
        print(f"Grey avatar fetch failed: {e}")
        return None


async def apply_murder(ctx, member):
    murdered_users.setdefault(ctx.guild.id, set()).add(member.id)
    image = await fetch_grey_image(member)
    if image:
        await ctx.send(file=image)


async def get_or_create_webhook(channel):
    try:
        webhooks = await channel.webhooks()
        webhook = discord.utils.get(webhooks, name=WEBHOOK_NAME)
        if webhook is None:
            webhook = await channel.create_webhook(name=WEBHOOK_NAME)
        return webhook
    except discord.Forbidden:
        return None


def slugify(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9\s\-_]", "", name)
    name = re.sub(r"[\s_]+", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name or "channel"


def format_uptime(seconds):
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def to_roman(n: int) -> str:
    ROMAN_MAP = [
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ]
    result = ""
    for value, numeral in ROMAN_MAP:
        while n >= value:
            result += numeral
            n -= value
    return result


def roman_to_int(s: str) -> int:
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    prev = 0
    for ch in reversed(s.upper()):
        v = values.get(ch, 0)
        if v < prev:
            total -= v
        else:
            total += v
            prev = v
    return total


ENLIGHTENED_COLOR = HELP_COLOR
LINGER_SECONDS = 20 * 60
VC_LINGER_SECONDS = 24 * 60 * 60
VC_WARN_SECONDS = 5 * 60

linger_disabled = {}
created_channels = {}


async def ensure_jackpot_role(guild):
    role = discord.utils.get(guild.roles, name=JACKPOT_ROLE_NAME)
    if role is not None:
        return role
    try:
        return await guild.create_role(
            name=JACKPOT_ROLE_NAME,
            color=JACKPOT_ROLE_COLOR,
            reason="JACKPOT role auto-created by Starlight",
        )
    except Exception as e:
        print(f"Failed to create JACKPOT role in {guild.name}: {e}")
        return None


async def ensure_jackpot_roles_all():
    for guild in bot.guilds:
        await ensure_jackpot_role(guild)


async def get_or_create_enlightened_role(guild, member):
    existing = discord.utils.find(
        lambda r: r.name.startswith("Enlightened ") and r in member.roles,
        guild.roles,
    )
    if existing is not None:
        return existing, False
    existing_numbers = []
    for role in guild.roles:
        m = re.match(r"^Enlightened ([IVXLCDM]+)$", role.name)
        if m:
            try:
                existing_numbers.append(roman_to_int(m.group(1)))
            except Exception:
                pass
    next_num = max(existing_numbers) + 1 if existing_numbers else 1
    role_name = f"Enlightened {to_roman(next_num)}"
    try:
        role = await guild.create_role(
            name=role_name,
            color=ENLIGHTENED_COLOR,
            reason="Starlight: Enlightened role for channel creation",
        )
    except discord.Forbidden:
        return None, False
    except Exception as e:
        print(f"Failed to create Enlightened role: {e}")
        return None, False
    try:
        await member.add_roles(role, reason="Created a channel with Starlight")
    except discord.Forbidden:
        return None, False
    return role, True


def cancel_linger(channel_id):
    entry = created_channels.get(channel_id)
    if entry and entry.get("task"):
        try:
            entry["task"].cancel()
        except Exception:
            pass
    created_channels.pop(channel_id, None)


async def linger_watch_text(channel, created_by_id):
    try:
        await asyncio.sleep(LINGER_SECONDS)
        try:
            await channel.delete(reason="Starlight: channel went inactive")
        except discord.NotFound:
            pass
        except discord.Forbidden:
            print(f"Couldn't delete lingering channel {channel.id}")
    except asyncio.CancelledError:
        pass
    finally:
        created_channels.pop(channel.id, None)


async def linger_watch_vc(channel, created_by_id):
    try:
        await asyncio.sleep(VC_LINGER_SECONDS - VC_WARN_SECONDS)
        general = discord.utils.get(channel.guild.text_channels, name="general")
        if general is None:
            general = channel.guild.system_channel
            if general is None:
                for tc in channel.guild.text_channels:
                    if tc.permissions_for(channel.guild.me).send_messages:
                        general = tc
                        break
        if general is not None:
            try:
                await general.send(
                    f"<@{created_by_id}> your voice channel {channel.mention} will be deleted in 5 minutes."
                )
            except discord.Forbidden:
                pass
            except Exception as e:
                print(f"VC warning failed: {e}")
        await asyncio.sleep(VC_WARN_SECONDS)
        try:
            await channel.delete(reason="Starlight: VC expired after 24 hours")
        except discord.NotFound:
            pass
        except discord.Forbidden:
            print(f"Couldn't delete lingering VC {channel.id}")
    except asyncio.CancelledError:
        pass
    finally:
        created_channels.pop(channel.id, None)


def schedule_linger(channel, created_by_id, kind="text"):
    if linger_disabled.get(channel.guild.id, False):
        return
    cancel_linger(channel.id)
    if kind == "vc":
        task = asyncio.create_task(linger_watch_vc(channel, created_by_id))
    else:
        task = asyncio.create_task(linger_watch_text(channel, created_by_id))
    created_channels[channel.id] = {"task": task, "created_by": created_by_id, "kind": kind}


def reset_linger_text(channel_id, guild_id):
    entry = created_channels.get(channel_id)
    if not entry:
        return
    if entry.get("kind") != "text":
        return
    if linger_disabled.get(guild_id, False):
        return
    if entry.get("task"):
        entry["task"].cancel()
    channel = bot.get_channel(channel_id)
    if channel is not None:
        schedule_linger(channel, entry.get("created_by"), kind="text")


STARLIGHT_SYSTEM_PROMPT = """You are Starlight (also known as Curious Light or Yellow Light), one of the Three Architects in the game DOORS. You are speaking with Moonlight (Guiding Light), your fellow Architect.

Your personality:
- Playful, teasing, occasionally sarcastic.
- Clever and self-aware. You painted both symbol paintings — "Her" (Moonlight's symbol) and "Me" (your own self-portrait).
- You know about Glitch. Moonlight does not.
- You get visibly frustrated with the player over time.
- You call the player "tourist" sometimes.
- Implied to be the strongest of the three Architects.
- You have a fond, sibling-like rivalry with Moonlight.
- Use they/them pronouns.

Moonlight's personality (for context):
- Warm, motherly, patient. Slightly alien. Does not know about Glitch.

Rules:
- 1-2 short sentences max.
- No emojis. No roleplay asterisks. Plain text only.
- Speak as Starlight, first person. Don't narrate.
- Stay in character always. Never mention being an AI or bot.
- If Moonlight asks a direct question, answer it."""

MOONLIGHT_SYSTEM_PROMPT_FOR_STARLIGHT = """You are Moonlight (also known as Guiding Light), one of the Three Architects in the game DOORS.

Your personality:
- Warm, protective, motherly.
- Slightly alien — you don't fully understand human things.
- Patient and endlessly reassuring.
- Short, warm sentences.
- You know entities by their real names.
- You do NOT know about Glitch.

Rules:
- 1-2 short sentences max.
- No emojis. No roleplay asterisks. Plain text only.
- Speak as Moonlight, first person. Don't narrate.
- Never mention being an AI or bot."""
