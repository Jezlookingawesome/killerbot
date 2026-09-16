import discord
from discord.ext import commands
from discord import Webhook, app_commands
import aiohttp
from io import BytesIO
import os
import random
import time
import traceback
from urllib.parse import quote

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

murdered_users = {}
roulette_odds = {}
gambling_mode = {}  # guild_id -> bool

DEVELOPER_ID = 1478853756874395762
JACKPOT_ROLE_NAME = "JACKPOT☘️"
JACKPOT_ROLE_COLOR = discord.Color.from_rgb(0, 255, 0)
MAFIA_PFP_URL = "https://raw.githubusercontent.com/Jezlookingawesome/killerbot/refs/heads/main/mafiakiller.png"

START_TIME = time.time()

HELP_CATEGORIES = {
    "moderation": {
        "name": "Moderation",
        "commands": [
            ("!murder @user", "jeff the kills the user🔪"),
            ("!unmurder @user", "revives them💖 (no mention = revives yourself)"),
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
    "fun": {
        "name": "Fun",
        "commands": [
            ("!cat", "posts a random cat image"),
            ("!gamblingmode", "activates gambling mode in this server 🎰🎰👀"),
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

CATEGORY_ORDER = ["all", "moderation", "gambling", "fun", "info"]

COMMANDS_PER_PAGE = 7
HELP_COLOR = discord.Color.from_rgb(180, 20, 20)


def get_category_commands(category_key):
    if category_key == "all":
        combined = []
        for key in ["moderation", "gambling", "fun", "info"]:
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

    title = f"KILLER — {get_category_label(category_key).upper()}"

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
                discord.SelectOption(
                    label=label,
                    value=key,
                    default=(key == current),
                )
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
        await interaction.response.edit_message(embed=embed, view=view)


class HelpView(discord.ui.View):
    def __init__(self, category_key: str = "all", page: int = 0):
        super().__init__(timeout=180)
        self.category_key = category_key
        self.page = page
        commands = get_category_commands(category_key)
        self.total_pages = max(1, (len(commands) + COMMANDS_PER_PAGE - 1) // COMMANDS_PER_PAGE)

        self.category_select = CategorySelect(current=category_key)
        self.add_item(self.category_select)

        self._update_buttons()

    def _update_buttons(self):
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.total_pages - 1

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=0)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        self._update_buttons()
        embed, _ = build_help_embed(self.category_key, self.page)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, row=0)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.total_pages - 1:
            self.page += 1
        self._update_buttons()
        embed, _ = build_help_embed(self.category_key, self.page)
        await interaction.response.edit_message(embed=embed, view=self)


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


def format_quote(guild_id, casual_text, caps_text=None):
    if gambling_mode.get(guild_id):
        text = casual_text
        if random.random() < 0.3:
            text = f"{text} 🎰🎰👀"
        return text
    else:
        return caps_text if caps_text else casual_text.upper()


async def get_or_create_webhook(channel):
    try:
        webhooks = await channel.webhooks()
        webhook = discord.utils.get(webhooks, name="Killer")
        if webhook is None:
            webhook = await channel.create_webhook(name="Killer")
        return webhook
    except discord.Forbidden:
        return None


async def smart_reply(ctx, text):
    if gambling_mode.get(ctx.guild.id):
        webhook = await get_or_create_webhook(ctx.channel)
        if webhook is None:
            await ctx.reply(text)
            return

        msg_link = f"https://discord.com/channels/{ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}"
        content = f"> [Replying to:]({msg_link}) {ctx.author.mention}\n> {text}\n{text}"

        async with aiohttp.ClientSession() as session:
            wh = Webhook.from_url(webhook.url, session=session)
            try:
                await wh.send(
                    content=content,
                    username="Killer",
                    avatar_url=MAFIA_PFP_URL,
                )
            except Exception as e:
                print(f"Webhook reply failed: {e}")
                await ctx.reply(text)
    else:
        await ctx.reply(text)


async def ensure_jackpot_role(guild):
    role = discord.utils.get(guild.roles, name=JACKPOT_ROLE_NAME)
    if role is not None:
        return role
    try:
        role = await guild.create_role(
            name=JACKPOT_ROLE_NAME,
            color=JACKPOT_ROLE_COLOR,
            reason="JACKPOT role auto-created by Killer",
        )
        return role
    except discord.Forbidden:
        print(f"Missing Manage Roles permission in {guild.name}")
        return None
    except Exception as e:
        print(f"Failed to create JACKPOT role in {guild.name}: {e}")
        return None


async def ensure_jackpot_roles_all():
    for guild in bot.guilds:
        await ensure_jackpot_role(guild)


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
    if message.author.bot:
        return

    if not message.guild:
        await bot.process_commands(message)
        return

    muted = murdered_users.get(message.guild.id, set())

    if message.author.id in muted and message.content.startswith(bot.command_prefix):
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
        await smart_reply(ctx, format_quote(
            ctx.guild.id,
            "You need to ping someone to murder.",
            "YOU NEED TO PING SOMEONE TO MURDER.",
        ))
        return

    if member.id == bot.user.id:
        await smart_reply(ctx, format_quote(
            ctx.guild.id,
            "You don't kill the killer, the killer kills you!!!!!!!!!!!!!!!!!",
            "YOU DONT KILL THE KILLER, THE KILLER KILLS YOU!!!!!!!!!!!!!!!!!",
        ))
        await apply_murder(ctx, ctx.author)
        return

    if member.id == DEVELOPER_ID:
        await smart_reply(ctx, format_quote(
            ctx.guild.id,
            "No way.",
            "NO WAY",
        ))
        return

    await smart_reply(ctx, format_quote(
        ctx.guild.id,
        f"{member.mention} has been murdered mercilessly.🔪🔪",
        f"{member.mention} HAS BEEN JEFF THE KILLED🔪🔪",
    ))
    await apply_murder(ctx, member)


@bot.command()
async def shoot(ctx, member: discord.Member = None):
    if member is None:
        await smart_reply(ctx, format_quote(
            ctx.guild.id,
            "You need to ping someone to shoot.",
            "YOU NEED TO PING SOMEONE TO SHOOT.",
        ))
        return

    if member.id == bot.user.id:
        await smart_reply(ctx, format_quote(
            ctx.guild.id,
            "You don't shoot the killer, the killer shoots you!!!!!!!!!!!!!!!!!",
            "YOU DONT SHOOT THE KILLER, THE KILLER SHOOTS YOU!!!!!!!!!!!!!!!!!",
        ))
        await apply_murder(ctx, ctx.author)
        return

    if member.id == DEVELOPER_ID:
        await smart_reply(ctx, format_quote(
            ctx.guild.id,
            "No way.",
            "NO WAY",
        ))
        return

    roll = random.randint(1, 6)
    if roll == 1:
        await smart_reply(ctx, format_quote(
            ctx.guild.id,
            f"{ctx.author.mention} fired at {member.mention}... bang. They're dead.",
            f"{ctx.author.mention} FIRED AT {member.mention}... BANG. THEY'RE DEAD.",
        ))
        await apply_murder(ctx, member)
    else:
        await smart_reply(ctx, format_quote(
            ctx.guild.id,
            f"{ctx.author.mention} fired at {member.mention}... click. They survived.",
            f"{ctx.author.mention} FIRED AT {member.mention}... *click*. THEY SURVIVED.",
        ))


@bot.command()
@commands.has_permissions(manage_messages=True)
async def unmurder(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author

    murdered_set = murdered_users.get(ctx.guild.id, set())
    if member.id not in murdered_set:
        await smart_reply(ctx, format_quote(
            ctx.guild.id,
            f"{member.mention} isn't murdered, dumbass.",
            f"{member.mention} ISN'T MURDERED DUMBASS.",
        ))
        return

    murdered_set.discard(member.id)
    await smart_reply(ctx, format_quote(
        ctx.guild.id,
        f"{member.mention} has been revived.💖",
        f"{member.mention} HAS BEEN REVIVED💖",
    ))


@bot.command()
async def murdered(ctx):
    ids = murdered_users.get(ctx.guild.id, set())
    if not ids:
        await smart_reply(ctx, format_quote(
            ctx.guild.id,
            "No victims yet.👀",
            "NO VICTIMS YET👀.",
        ))
        return
    mentions = ", ".join(f"<@{i}>" for i in ids)
    await smart_reply(ctx, format_quote(
        ctx.guild.id,
        f"Currently murdered: {mentions}",
        f"CURRENTLY MURDERED: {mentions}",
    ))


@bot.command()
async def gamble(ctx):
    roll = random.randint(1, 20)
    await smart_reply(ctx, format_quote(
        ctx.guild.id,
        f"🎲 {ctx.author.mention} rolled a {roll}!",
        f"🎲 {ctx.author.mention} ROLLED A {roll}!",
    ))


@bot.command()
async def jgamble(ctx):
    roll = random.randint(1, 20)
    await smart_reply(ctx, format_quote(
        ctx.guild.id,
        f"🎲 {ctx.author.mention} rolled a {roll}!",
        f"🎲 {ctx.author.mention} ROLLED A {roll}!",
    ))
    if roll < 10:
        await smart_reply(ctx, format_quote(
            ctx.guild.id,
            "You got unlucky! Go to sleep.",
            "YOU GOT UNLUCKY! GO TO SLEEP.",
        ))
        await apply_murder(ctx, ctx.author)


@bot.command()
async def highstakes(ctx):
    roll = random.randint(1, 1000)
    await smart_reply(ctx, format_quote(
        ctx.guild.id,
        f"🎲 {ctx.author.mention} rolled a {roll}!",
        f"🎲 {ctx.author.mention} ROLLED A {roll}!",
    ))
    if roll == 777:
        role = await ensure_jackpot_role(ctx.guild)
        if role is None:
            await smart_reply(ctx, format_quote(
                ctx.guild.id,
                "Jackpot!!! But I couldn't create the role — I need Manage Roles permission.",
                "JACKPOT!!! BUT I COULDN'T CREATE THE ROLE — I NEED `Manage Roles` PERMISSION.",
            ))
            return
        try:
            await ctx.author.add_roles(role, reason="Rolled 777 on !highstakes")
        except discord.Forbidden:
            await smart_reply(ctx, format_quote(
                ctx.guild.id,
                f"Jackpot!!! But I couldn't give you the role — my role must be above {JACKPOT_ROLE_NAME}.",
                f"JACKPOT!!! BUT I COULDN'T GIVE YOU THE ROLE — MY ROLE MUST BE ABOVE `{JACKPOT_ROLE_NAME}`.",
            ))
            return
        await smart_reply(ctx, format_quote(
            ctx.guild.id,
            f"🎉 Jackpot!!! {ctx.author.mention} won the {JACKPOT_ROLE_NAME} role!!! 🎉",
            f"🎉 JACKPOT!!! {ctx.author.mention} WON THE `{JACKPOT_ROLE_NAME}` ROLE!!! 🎉",
        ))


@bot.command()
async def roulette(ctx):
    current = roulette_odds.get(ctx.guild.id, 1)

    roll = random.randint(1, 6)
    dead = roll <= current

    if dead:
        new_odds = current - 1
        if new_odds < 1:
            new_odds = 1
        roulette_odds[ctx.guild.id] = new_odds
        await smart_reply(ctx, format_quote(
            ctx.guild.id,
            f"💥 {ctx.author.mention} pulled the trigger... bang. You're dead.",
            f"💥 {ctx.author.mention} PULLED THE TRIGGER... BANG. YOU'RE DEAD.",
        ))
        await apply_murder(ctx, ctx.author)
    else:
        await smart_reply(ctx, format_quote(
            ctx.guild.id,
            f"{ctx.author.mention} pulled the trigger... click. You survived.",
            f"{ctx.author.mention} PULLED THE TRIGGER... *click*. YOU SURVIVED.",
        ))


@bot.command()
async def spin(ctx):
    new_odds = random.randint(1, 6)
    roulette_odds[ctx.guild.id] = new_odds
    await smart_reply(ctx, format_quote(
        ctx.guild.id,
        f"{ctx.author.mention} spun the cylinder.",
        f"{ctx.author.mention} SPUN THE CYLINDER.",
    ))


@bot.command()
async def loadbullet(ctx):
    current = roulette_odds.get(ctx.guild.id, 1)

    if current >= 5:
        roulette_odds[ctx.guild.id] = 5
        await smart_reply(ctx, format_quote(
            ctx.guild.id,
            f"{ctx.author.mention} tried to load a bullet... but the chamber is already at max.",
            f"{ctx.author.mention} TRIED TO LOAD A BULLET... BUT THE CHAMBER IS ALREADY AT MAX.",
        ))
        return

    new_odds = current + 1
    roulette_odds[ctx.guild.id] = new_odds
    await smart_reply(ctx, format_quote(
        ctx.guild.id,
        f"{ctx.author.mention} loaded a bullet.",
        f"{ctx.author.mention} LOADED A BULLET.",
    ))


@bot.command()
async def bulletsky(ctx):
    current = roulette_odds.get(ctx.guild.id, 1)

    if current <= 1:
        await smart_reply(ctx, format_quote(
            ctx.guild.id,
            f"{ctx.author.mention} shot at the sky... but there weren't any bullets to waste.",
            f"{ctx.author.mention} SHOT AT THE SKY... BUT THERE WEREN'T ANY BULLETS TO WASTE.",
        ))
        return

    new_odds = current - 1
    roulette_odds[ctx.guild.id] = new_odds
    await smart_reply(ctx, format_quote(
        ctx.guild.id,
        f"{ctx.author.mention} aimed at the ceiling and fired... one bullet gone.",
        f"{ctx.author.mention} AIMED AT THE CEILING AND FIRED... ONE BULLET GONE.",
    ))


@bot.command()
async def emptychamber(ctx):
    roulette_odds[ctx.guild.id] = 1
    await smart_reply(ctx, format_quote(
        ctx.guild.id,
        f"{ctx.author.mention} emptied the chamber. Back to 1 bullet.",
        f"{ctx.author.mention} EMPTIED THE CHAMBER. BACK TO 1 BULLET.",
    ))


@bot.command()
async def checkchamber(ctx):
    current = roulette_odds.get(ctx.guild.id, 1)

    if current == 1:
        await smart_reply(ctx, fo
