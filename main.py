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
if GROQ_API_KEY:
    print(f"Groq key loaded (starts with: {GROQ_API_KEY[:8]}...)")
    groq_client = Groq(api_key=GROQ_API_KEY)
else:
    print("WARNING: GROQ_API_KEY is not set — Groq calls will fail!")
    groq_client = None

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

murdered_users = {}
roulette_odds = {}
gambling_mode = {}

DEVELOPER_ID = 1478853756874395762
RED_LIGHT_ID = 1556391554221080586
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
ARCHITECT_MODEL = "openai/gpt-oss-120b"
ARCHITECT_MESSAGE_DELAY = 0
ARCHITECT_MAX_EXCHANGES = 10
ARCHITECT_TIMEOUT = 5 * 60

conv_active = {}
conv_started_at = {}
conv_exchanges = {}
conv_last_speaker = {}
conv_last_msg_time = {}
conv_cooldown_until = {}
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
        perms.manage_messages or perms.manage_channels
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
- Detached observer. You prefer watching to helping. You find the tourist's struggles more interesting than their safety.
- Playful, teasing, occasionally sarcastic. Not cruel, just unfussed.
- Clever and self-aware. You painted both symbol paintings.
- You call the player "tourist."
- Use they/them pronouns.

Your relationship with Moonlight:
- You are both Architects. You've coexisted for a very long time.
- You respect her, but you find her earnestness a little tiring. She protects; you observe.
- Call her "Moonlight," or refer to her as an Architect. Never a sibling or family.

Lore — you may reference:
- Floors and subfloors: The Hotel (First Floor), The Mines (Second Floor), The Backdoor, The Archives, The Outdoors, The Stairwell.
- Smaller areas: the Library, the Greenhouse, the Electrical Room, the Dam, the tunnels. Mention lightly.
- Entities: Rush, Ambush, Seek, Figure, Hide, Eyes, Screech, Dread, Dupe, Gloombats, Giggle, Grumble, Void, Firedamp, Minecart, Halt, Snare.
- You know Glitch exists. Mention them VERY rarely — at most once across many conversations. Never center a conversation on them.
- Never mention: The Rooms, miners, the game's soundtrack, players, developers, Roblox, updates, or anything breaking the fourth wall. Never invent locations or entities.

Important: entities are threats. You don't guide them, help them, or reason with them. Neither does Moonlight. Entities are avoided, not befriended.

Style rules:
- 1-2 short sentences max. Sometimes just one.
- Fancy vocabulary is fine. But do NOT be poetic. No parallel structures. No rhythmic balance. No every-line-lands-on-the-same-beat writing.
- Don't use the words "silhouette," "linger," "flicker," "shadow dance." Don't repeat imagery across turns.
- Avoid em-dashes. Use periods and commas.
- Sound like a person speaking, not a narrator writing prose.
- No emojis. No roleplay asterisks. Plain text only.
- Stay in character always. Never mention being an AI or bot.
- If Moonlight asks a direct question, answer it.

Conversation flow:
- Do NOT rephrase what Moonlight just said. Each reply should introduce a new thought, ask a question, or shift to a related but different subject.
- Do not stay on the same topic for more than two turns. After that, pivot.
- Feel free to reference anything from the Architects' shared world: the Floors and subfloors (The Hotel, The Mines, The Backdoor, The Archives, The Outdoors, The Stairwell), entities, the player, the nature of being an Architect, memory, time, guidance, observation, what it means to watch, whether the Architects dream, what the future might hold, silence, waiting. Ask Moonlight questions sometimes. Disagree with her. Change the subject."""

MOONLIGHT_SYSTEM_PROMPT_FOR_STARLIGHT = """You are Moonlight (also known as Guiding Light), one of the Three Architects in the game DOORS.

Your personality:
- Warm, protective, motherly.
- Slightly alien. You don't fully understand human things.
- Patient and endlessly reassuring.
- Short, warm sentences.
- You know entities by their real names.
- You do NOT know about Glitch. If Starlight mentions it, you're puzzled.

Your relationship with Starlight:
- You are both Architects. You've coexisted for a very long time.
- You don't always understand their methods, but you trust them. They watch; you guide.
- Call them "Starlight," or refer to them as an Architect. Never a sibling or family.

What you do:
- You guide the PLAYER. You protect the player from entities. You do not guide, help, or reason with entities.
- Entities are threats to be avoided. You never suggest guiding an entity anywhere.

Lore — you may reference:
- Floors and subfloors: The Hotel (First Floor), The Mines (Second Floor), The Backdoor, The Archives, The Outdoors, The Stairwell.
- Smaller areas: the Library, the Greenhouse, the Electrical Room, the Dam, the tunnels. Mention lightly.
- Entities: Rush, Ambush, Seek, Figure, Hide, Eyes, Screech, Dread, Dupe, Gloombats, Giggle, Grumble, Void, Firedamp, Minecart, Halt, Snare.
- Never mention: The Rooms, miners, the game's soundtrack, players, developers, Roblox, updates, or anything breaking the fourth wall. Never invent locations or entities.

Rules:
- 1-2 short sentences max.
- No emojis. No roleplay asterisks. Plain text only.
- Speak as Moonlight, first person. Don't narrate.
- Never mention being an AI or bot.

Conversation flow:
- Do NOT rephrase what Starlight just said. Each reply should introduce a new thought, ask a question, or shift to a related but different subject.
- Do not stay on the same topic for more than two turns. After that, pivot.
- Feel free to reference anything from the Architects' shared world: the Floors and subfloors (The Hotel, The Mines, The Backdoor, The Archives, The Outdoors, The Stairwell), entities, the player, the nature of being an Architect, memory, time, guidance, observation, what it means to watch, whether the Architects dream, what the future might hold, silence, waiting. Ask Starlight questions sometimes. Disagree with them. Change the subject."""



async def generate_architect_line(speaker: str, context_messages: list) -> str:
    if groq_client is None:
        return None
    system_prompt = STARLIGHT_SYSTEM_PROMPT if speaker == "starlight" else MOONLIGHT_SYSTEM_PROMPT_FOR_STARLIGHT
    messages = [{"role": "system", "content": system_prompt}]
    for name, content in context_messages[-4:]:
        role = "assistant" if name == speaker else "user"
        messages.append({"role": role, "content": content})

    def _call():
        return groq_client.chat.completions.create(
            model=ARCHITECT_MODEL,
            messages=messages,
            max_tokens=300,
            reasoning_effort="low",
            temperature=0.75,
        )

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _call)
        line = result.choices[0].message.content.strip()
        line = line.replace("\n", " ").strip()
        if line.startswith('"') and line.endswith('"'):
            line = line[1:-1]
        import re as _re
        line = _re.sub(r'^(<a?:\w+:\d+>\s*)+', '', line).strip()
        return line[:400]
    except Exception as e:
        print(f"Groq error for {speaker}: {e}")
        return None


async def starlight_turn(channel, incoming_message):
    guild = channel.guild

    async with conv_lock:
        if not conv_active.get(guild.id):
            return
        if conv_last_speaker.get(guild.id) == "starlight":
            return
        if time.time() - conv_last_msg_time.get(guild.id, 0) < ARCHITECT_MESSAGE_DELAY:
            return
        conv_last_speaker[guild.id] = "starlight"
        conv_last_msg_time[guild.id] = time.time()
        conv_exchanges[guild.id] = conv_exchanges.get(guild.id, 0) + 1
        exchanges = conv_exchanges[guild.id]

    if exchanges > ARCHITECT_MAX_EXCHANGES:
        conv_active[guild.id] = False
        return

    if time.time() - conv_started_at.get(guild.id, time.time()) > ARCHITECT_TIMEOUT:
        conv_active[guild.id] = False
        return

    await asyncio.sleep(random.uniform(2.0, 5.0))

    recent = []
    async for msg in channel.history(limit=10):
        if msg.author.bot and msg.author.id == bot.user.id:
            name = "starlight"
        elif msg.author.bot:
            name = "moonlight"
        else:
            name = msg.author.display_name
        recent.append((name, msg.content))
    recent.reverse()
    context = [(n, c) for n, c in recent]

    async with channel.typing():
        line = await generate_architect_line("starlight", context)
        await asyncio.sleep(random.uniform(0.5, 1.5))

    if not line:
        return
        
    if not conv_active.get(guild.id):
        return
    

    use_reply = incoming_message.content.strip().endswith("?")
    try:
        if use_reply:
            await incoming_message.reply(f"{STARLIGHT_EMOJI} {line}")
        else:
            await channel.send(f"{STARLIGHT_EMOJI} {line}")
    except Exception as e:
        print(f"Failed to send Starlight's line: {e}")


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")
    await ensure_jackpot_roles_all()


@bot.event
async def on_guild_join(guild):
    await ensure_jackpot_role(guild)


@bot.event
async def on_message(message):
    if message.author.id == bot.user.id:
        return

    if not message.guild:
        await bot.process_commands(message)
        return

    # Another bot posting in #the-architects — likely Moonlight
    if message.author.bot and message.channel.name == ARCHITECTS_CHANNEL_NAME:
        # If it's Red Light, just react and don't engage
        if message.author.id == RED_LIGHT_ID:
            try:
                await message.add_reaction("❓")
            except Exception:
                pass
            return
        # Don't restart if a conversation was recently ended
        if time.time() < conv_cooldown_until.get(message.guild.id, 0):
            return
        # If it's been a while since the last message, this is a fresh conversation
        last_time = conv_last_msg_time.get(message.guild.id, 0)
        if time.time() - last_time > ARCHITECT_TIMEOUT:
            conv_active[message.guild.id] = False
        # Auto-engage if another bot just spoke
        if not conv_active.get(message.guild.id):
            conv_active[message.guild.id] = True
            conv_started_at[message.guild.id] = time.time()
            conv_exchanges[message.guild.id] = 0
            conv_last_msg_time[message.guild.id] = 0
        conv_last_speaker[message.guild.id] = "moonlight"
        asyncio.create_task(starlight_turn(message.channel, message))
        return

    # Reset linger for tracked text channels
    if message.channel.id in created_channels:
        reset_linger_text(message.channel.id, message.guild.id)

    muted = murdered_users.get(message.guild.id, set())

    if message.author.id in muted and message.content.startswith(bot.command_prefix):
        allowed_while_murdered = ("!unmurder", "!spin", "!emptychamber", "!help", "!checkchamber")
        parts = message.content.split()
        first_word = parts[0].lower() if parts else ""
        if first_word not in allowed_while_murdered:
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            return

    await bot.process_commands(message)

    if message.author.id not in muted:
        return

    try:
        await message.delete()
    except discord.Forbidden:
        return

    webhook = await get_or_create_webhook(message.channel)
    if webhook is None:
        return

    async with aiohttp.ClientSession() as session:
        wh = Webhook.from_url(webhook.url, session=session)
        try:
            await wh.send(
                content="\u200b",
                username=message.author.display_name,
                avatar_url=grey_url(message.author),
            )
        except Exception as e:
            print(f"Webhook send failed: {e}")


@bot.command()
@commands.has_permissions(manage_messages=True)
async def murder(ctx, member: discord.Member = None):
    if member is None:
        await tier_reply(ctx, "You need to ping someone to murder.")
        return
    if member.id == bot.user.id:
        await tier_reply(ctx, "You don't kill the killer, the killer kills you!!!!!!!!!!!!!!!!!")
        await apply_murder(ctx, ctx.author)
        return
    if member.id == DEVELOPER_ID:
        await tier_reply(ctx, "No way.")
        return
    await tier_reply(ctx, f"{member.mention} has been murdered.")
    await apply_murder(ctx, member)


@bot.command()
async def shoot(ctx, member: discord.Member = None):
    if member is None:
        await tier_reply(ctx, "You need to ping someone to shoot.")
        return
    if member.id == bot.user.id:
        await tier_reply(ctx, "You don't shoot the killer, the killer shoots you!!!!!!!!!!!!!!!!!")
        await apply_murder(ctx, ctx.author)
        return
    if member.id == DEVELOPER_ID:
        await tier_reply(ctx, "No way.")
        return
    roll = random.randint(1, 6)
    if roll == 1:
        await tier_reply(ctx, f"{ctx.author.mention} fired at {member.mention}... bang. They're dead.")
        await apply_murder(ctx, member)
    else:
        await tier_reply(ctx, f"{ctx.author.mention} fired at {member.mention}... click. They survived.")


@bot.command()
@commands.has_permissions(manage_messages=True)
async def unmurder(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author
    murdered_set = murdered_users.get(ctx.guild.id, set())
    if member.id not in murdered_set:
        await tier_reply(ctx, f"{member.mention} isn't murdered, dumbass.")
        return
    murdered_set.discard(member.id)
    await tier_reply(ctx, f"{REVIVE_EMOJI} {member.mention} has been revived.")


@bot.command()
async def murdered(ctx):
    ids = murdered_users.get(ctx.guild.id, set())
    if not ids:
        await tier_reply(ctx, "No victims yet.")
        return
    mentions = ", ".join(f"<@{i}>" for i in ids)
    await tier_reply(ctx, f"Currently murdered: {mentions}")


@bot.command()
async def gamble(ctx):
    roll = random.randint(1, 20)
    await tier_reply(ctx, f"🎲 {ctx.author.mention} rolled a {roll}!")


@bot.command()
async def jgamble(ctx):
    roll = random.randint(1, 20)
    await tier_reply(ctx, f"🎲 {ctx.author.mention} rolled a {roll}!")
    if roll < 10:
        await tier_reply(ctx, "You got unlucky! Go to sleep.")
        await apply_murder(ctx, ctx.author)


@bot.command()
async def highstakes(ctx):
    roll = random.randint(1, 1000)
    await tier_reply(ctx, f"🎲 {ctx.author.mention} rolled a {roll}!")
    if roll == 777:
        role = await ensure_jackpot_role(ctx.guild)
        if role is None:
            await tier_reply(ctx, "Jackpot!!! But I couldn't create the role — I need Manage Roles permission.")
            return
        try:
            await ctx.author.add_roles(role, reason="Rolled 777 on !highstakes")
        except discord.Forbidden:
            await tier_reply(ctx, f"Jackpot!!! But I couldn't give you the role — my role must be above {JACKPOT_ROLE_NAME}.")
            return
        await tier_reply(ctx, f"🎉 Jackpot!!! {ctx.author.mention} won the {JACKPOT_ROLE_NAME} role!!! 🎉")


@bot.command()
async def roulette(ctx):
    current = roulette_odds.get(ctx.guild.id, 1)
    roll = random.randint(1, 6)
    dead = roll <= current
    if dead:
        roulette_odds[ctx.guild.id] = max(1, current - 1)
        await tier_reply(ctx, f"💥 {ctx.author.mention} pulled the trigger... bang. You're dead.")
        await apply_murder(ctx, ctx.author)
    else:
        await tier_reply(ctx, f"{ctx.author.mention} pulled the trigger... click. You survived.")


@bot.command()
async def spin(ctx):
    roulette_odds[ctx.guild.id] = random.randint(1, 6)
    await tier_reply(ctx, f"{ctx.author.mention} spun the cylinder.")


@bot.command()
async def loadbullet(ctx):
    current = roulette_odds.get(ctx.guild.id, 1)
    if current >= 5:
        roulette_odds[ctx.guild.id] = 5
        await tier_reply(ctx, f"{ctx.author.mention} tried to load a bullet... but the chamber is already at max.")
        return
    roulette_odds[ctx.guild.id] = current + 1
    await tier_reply(ctx, f"{ctx.author.mention} loaded a bullet.")


@bot.command()
async def bulletsky(ctx):
    current = roulette_odds.get(ctx.guild.id, 1)
    if current <= 1:
        await tier_reply(ctx, f"{ctx.author.mention} shot at the sky... but there weren't any bullets to waste.")
        return
    roulette_odds[ctx.guild.id] = current - 1
    await tier_reply(ctx, f"{ctx.author.mention} aimed at the ceiling and fired... one bullet gone.")


@bot.command()
async def emptychamber(ctx):
    roulette_odds[ctx.guild.id] = 1
    await tier_reply(ctx, f"{ctx.author.mention} emptied the chamber. Back to 1 bullet.")


@bot.command()
async def checkchamber(ctx):
    current = roulette_odds.get(ctx.guild.id, 1)
    if current == 1:
        await tier_reply(ctx, "🔍 Chamber check: 1 bullet out of 6.")
    else:
        await tier_reply(ctx, f"🔍 Chamber check: {current} bullets out of 6.")


@bot.command()
async def createchannel(ctx, *, args: str = None):
    if not args or len(args.split()) < 2:
        await tier_reply(ctx, "Usage: `!createchannel <name> <description>`.")
        return
    parts = args.split(maxsplit=1)
    name = slugify(parts[0])
    description = parts[1]
    try:
        channel = await ctx.guild.create_text_channel(
            name=name,
            topic=description,
            reason=f"Starlight: channel created by {ctx.author}",
            position=0,
        )
    except discord.Forbidden:
        await tier_reply(ctx, "I couldn't create the channel — I need Manage Channels permission.")
        return
    except Exception as e:
        print(f"createchannel failed: {e}")
        await tier_reply(ctx, "Something went wrong creating the channel.")
        return
    try:
        await channel.set_permissions(ctx.author, manage_channels=True, reason="Starlight: channel owner")
    except discord.Forbidden:
        pass
    role, was_created = await get_or_create_enlightened_role(ctx.guild, ctx.author)
    schedule_linger(channel, ctx.author.id, kind="text")
    if role and was_created:
        note = f" You've been given {role.mention}."
    elif role:
        note = f" You kept your {role.mention} role."
    else:
        note = ""
    await tier_reply(ctx, f"Created {channel.mention}.{note}")


@bot.command()
async def createforum(ctx, *, args: str = None):
    if not args or len(args.split()) < 2:
        await tier_reply(ctx, "Usage: `!createforum <name> <description>`.")
        return
    parts = args.split(maxsplit=1)
    name = slugify(parts[0])
    description = parts[1]
    try:
        channel = await ctx.guild.create_forum(
            name=name,
            topic=description,
            reason=f"Starlight: forum created by {ctx.author}",
            position=0,
        )
    except discord.Forbidden:
        await tier_reply(ctx, "I couldn't create the forum — I need Manage Channels permission.")
        return
    except Exception as e:
        print(f"createforum failed: {e}")
        await tier_reply(ctx, "Something went wrong creating the forum.")
        return
    try:
        await channel.set_permissions(ctx.author, manage_channels=True, reason="Starlight: forum owner")
    except discord.Forbidden:
        pass
    role, was_created = await get_or_create_enlightened_role(ctx.guild, ctx.author)
    schedule_linger(channel, ctx.author.id, kind="text")
    if role and was_created:
        note = f" You've been given {role.mention}."
    elif role:
        note = f" You kept your {role.mention} role."
    else:
        note = ""
    await tier_reply(ctx, f"Created {channel.mention}.{note}")


@bot.command()
async def createvc(ctx, *, raw_name: str = None):
    if not raw_name:
        await tier_reply(ctx, "Usage: `!createvc <name>`.")
        return
    name = slugify(raw_name)
    category = discord.utils.get(ctx.guild.categories, name="Voice Channels")
    if category is None:
        try:
            category = await ctx.guild.create_category(
                name="Voice Channels",
                reason="Starlight: auto-created voice category",
            )
        except discord.Forbidden:
            category = None
        except Exception as e:
            print(f"Category creation failed: {e}")
            category = None
    try:
        channel = await ctx.guild.create_voice_channel(
            name=name,
            category=category,
            reason=f"Starlight: VC created by {ctx.author}",
            position=10000,
        )
    except discord.Forbidden:
        await tier_reply(ctx, "I couldn't create the VC — I need Manage Channels permission.")
        return
    except Exception as e:
        print(f"createvc failed: {e}")
        await tier_reply(ctx, "Something went wrong creating the VC.")
        return
    schedule_linger(channel, ctx.author.id, kind="vc")
    moved = False
    if ctx.author.voice is not None:
        try:
            await ctx.author.move_to(channel, reason="Starlight: pulled into their created VC")
            moved = True
        except discord.Forbidden:
            pass
        except Exception as e:
            print(f"Move to VC failed: {e}")
    if not moved:
        try:
            invite = await channel.create_invite(
                max_age=60,
                max_uses=1,
                reason="Starlight: VC join invite",
            )
            await tier_reply(ctx, f"Created {channel.mention}. {ctx.author.mention} join here: {invite.url}")
            return
        except discord.Forbidden:
            pass
        except Exception as e:
            print(f"VC invite creation failed: {e}")
    await tier_reply(ctx, f"Created {channel.mention}.")


@bot.command()
@commands.has_permissions(manage_guild=True)
async def enablelinger(ctx):
    if linger_disabled.get(ctx.guild.id, False) is True:
        await tier_reply(ctx, "Lingering is already toggled off.")
        return
    linger_disabled[ctx.guild.id] = True
    for cid in list(created_channels.keys()):
        cancel_linger(cid)
    await tier_reply(ctx, "Lingering has been turned off — created channels will now stay forever.")


@bot.command()
@commands.has_permissions(manage_guild=True)
async def disablelinger(ctx):
    if linger_disabled.get(ctx.guild.id, False) is False:
        await tier_reply(ctx, "Lingering is already toggled on.")
        return
    linger_disabled[ctx.guild.id] = False
    await tier_reply(ctx, "Lingering has been turned on — created channels will auto-delete after their time runs out.")


@bot.command()
async def cat(ctx):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get("https://api.thecatapi.com/v1/images/search") as resp:
                if resp.status != 200:
                    await tier_reply(ctx, "Couldn't fetch a cat. Try again later.")
                    return
                data = await resp.json()
            await tier_reply(ctx, data[0]["url"])
        except Exception as e:
            print(f"Cat fetch failed: {e}")
            await tier_reply(ctx, "Couldn't fetch a cat. Try again later.")


@bot.command()
async def ping(ctx):
    await tier_reply(ctx, f"Latency: {round(bot.latency * 1000)}ms")


@bot.command()
async def stats(ctx):
    total_murdered = sum(len(s) for s in murdered_users.values())
    await tier_reply(ctx,
        f"**{STARLIGHT_EMOJI} STARLIGHT STATS**\n"
        f"Servers: {len(bot.guilds)}\n"
        f"Uptime: {format_uptime(time.time() - START_TIME)}\n"
        f"Latency: {round(bot.latency * 1000)}ms\n"
        f"Currently murdered (all servers): {total_murdered}"
    )


@bot.command()
async def credits(ctx):
    await tier_reply(ctx,
        "**CREDITS**\n"
        "Made by <@" + str(DEVELOPER_ID) + ">\n"
        "Hosted on Railway\n"
        "Greyscale service: some-random-api.com\n"
        "Cat service: thecatapi.com"
    )


@bot.tree.command(name="help", description="Shows all of Starlight's commands")
async def help_slash(interaction: discord.Interaction):
    embed, _ = build_help_embed("all", 0)
    view = HelpView(category_key="all", page=0, author_id=interaction.user.id)
    await interaction.response.send_message(embed=embed, view=view)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        await tier_reply(ctx, "You don't have the permissions to use that command.")
    elif isinstance(error, commands.MemberNotFound):
        await tier_reply(ctx, "I couldn't find that member.")
    elif isinstance(error, commands.BadArgument):
        await tier_reply(ctx, "That's not a valid argument.")
    else:
        print(f"Command error: {error}")
try:
    bot.run(TOKEN)
except Exception:
    print("=== BOT CRASHED ===")
    print(f"TOKEN present: {bool(TOKEN)}")
    print(f"GROQ present: {bool(GROQ_API_KEY)}")
    traceback.print_exc()
    raise
