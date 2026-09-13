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

DEVELOPER_ID = 1478853756874395762
JACKPOT_ROLE_NAME = "JACKPOT☘️"
JACKPOT_ROLE_COLOR = discord.Color.from_rgb(0, 255, 0)

START_TIME = time.time()

# ----- HELP PAGES -----
# Each entry: (command usage, short description)
# Add new commands here. The paginator handles splitting into pages of 5.
HELP_ENTRIES = [
    ("!murder @user", "jeff the kills the user🔪"),
    ("!unmurder @user", "revives them💖 (no mention = revives yourself)"),
    ("!murdered", "lists everyone currently murdered"),
    ("!gamble", "rolls a d20"),
    ("!jgamble", "same as gamble, but if you roll below 10 you DIE"),
    ("!highstakes", "rolls a d1000"),
    ("!roulette", "1/6 chance of getting murdered"),
    ("!cat", "posts a random cat image"),
    ("!ping", "shows the bot's latency"),
    ("!stats", "shows bot stats"),
    ("!credits", "shows who made the bot"),
]

COMMANDS_PER_PAGE = 5
HELP_COLOR = discord.Color.from_rgb(180, 20, 20)  # blood red


def build_help_embed(page: int):
    total_pages = max(1, (len(HELP_ENTRIES) + COMMANDS_PER_PAGE - 1) // COMMANDS_PER_PAGE)
    page = max(0, min(page, total_pages - 1))

    start = page * COMMANDS_PER_PAGE
    end = start + COMMANDS_PER_PAGE
    chunk = HELP_ENTRIES[start:end]

    embed = discord.Embed(
        title="KILLER — COMMANDS",
        description=f"**Prefix: !**\nPage {page + 1}/{total_pages}",
        color=HELP_COLOR,
    )
    for usage, desc in chunk:
        embed.add_field(name=usage, value=desc, inline=False)
    embed.set_footer(text="Use the buttons below to flip pages")
    return embed, total_pages


class HelpView(discord.ui.View):
    def __init__(self, page: int = 0):
        super().__init__(timeout=180)
        self.page = page
        total_pages = max(1, (len(HELP_ENTRIES) + COMMANDS_PER_PAGE - 1) // COMMANDS_PER_PAGE)
        self.total_pages = total_pages
        self._update_buttons()

    def _update_buttons(self):
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.total_pages - 1

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        self._update_buttons()
        embed, _ = build_help_embed(self.page)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.total_pages - 1:
            self.page += 1
        self._update_buttons()
        embed, _ = build_help_embed(self.page)
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

    await bot.process_commands(message)

    if not message.guild:
        return

    muted = murdered_users.get(message.guild.id, set())
    if message.author.id not in muted:
        return
    if message.content.startswith(bot.command_prefix):
        return

    try:
        await message.delete()
    except discord.Forbidden:
        return

    try:
        webhooks = await message.channel.webhooks()
        webhook = discord.utils.get(webhooks, name="FakeMute")
        if webhook is None:
            webhook = await message.channel.create_webhook(name="FakeMute")
    except discord.Forbidden:
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
        await ctx.send("YOU NEED TO PING SOMEONE TO MURDER.")
        return

    if member.id == bot.user.id:
        await ctx.send("YOU DONT KILL THE KILLER, THE KILLER KILLS YOU!!!!!!!!!!!!!!!!!")
        await apply_murder(ctx, ctx.author)
        return

    if member.id == DEVELOPER_ID:
        await ctx.send("NO WAY")
        return

    await ctx.send(f"{member.mention} HAS BEEN JEFF THE KILLED🔪🔪")
    await apply_murder(ctx, member)


@bot.command()
@commands.has_permissions(manage_messages=True)
async def unmurder(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author

    murdered_set = murdered_users.get(ctx.guild.id, set())
    if member.id not in murdered_set:
        await ctx.send(f"{member.mention} ISN'T MURDERED DUMBASS.")
        return

    murdered_set.discard(member.id)
    await ctx.send(f"{member.mention} HAS BEEN REVIVED💖")


@bot.command()
async def murdered(ctx):
    ids = murdered_users.get(ctx.guild.id, set())
    if not ids:
        await ctx.send("NO VICTIMS YET👀.")
        return
    mentions = ", ".join(f"<@{i}>" for i in ids)
    await ctx.send(f"CURRENTLY MURDERED: {mentions}")


@bot.command()
async def gamble(ctx):
    roll = random.randint(1, 20)
    await ctx.send(f"🎲 {ctx.author.mention} ROLLED A {roll}!")


@bot.command()
async def jgamble(ctx):
    roll = random.randint(1, 20)
    await ctx.send(f"🎲 {ctx.author.mention} ROLLED A {roll}!")
    if roll < 10:
        await ctx.send("YOU GOT UNLUCKY! GO TO SLEEP.")
        await apply_murder(ctx, ctx.author)


@bot.command()
async def highstakes(ctx):
    roll = random.randint(1, 1000)
    await ctx.send(f"🎲 {ctx.author.mention} ROLLED A {roll}!")
    if roll == 777:
        role = await ensure_jackpot_role(ctx.guild)
        if role is None:
            await ctx.send("JACKPOT!!! BUT I COULDN'T CREATE THE ROLE — I NEED `Manage Roles` PERMISSION.")
            return
        try:
            await ctx.author.add_roles(role, reason="Rolled 777 on !highstakes")
        except discord.Forbidden:
            await ctx.send("JACKPOT!!! BUT I COULDN'T GIVE YOU THE ROLE — MY ROLE MUST BE ABOVE `JACKPOT☘️`.")
            return
        await ctx.send(f"🎉 JACKPOT!!! {ctx.author.mention} WON THE `{JACKPOT_ROLE_NAME}` ROLE!!! 🎉")


@bot.command()
async def roulette(ctx):
    chamber = random.randint(1, 6)
    if chamber == 1:
        await ctx.send(f"💥 {ctx.author.mention} PULLED THE TRIGGER... BANG. YOU'RE DEAD.")
        await apply_murder(ctx, ctx.author)
    else:
        await ctx.send(f"🔫 {ctx.author.mention} PULLED THE TRIGGER... *click*. YOU SURVIVED.")


@bot.command()
async def cat(ctx):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get("https://api.thecatapi.com/v1/images/search") as resp:
                if resp.status != 200:
                    await ctx.send("COULDN'T FETCH A CAT. TRY AGAIN LATER.")
                    return
                data = await resp.json()
            cat_url = data[0]["url"]
            await ctx.send(cat_url)
        except Exception as e:
            print(f"Cat fetch failed: {e}")
            await ctx.send("COULDN'T FETCH A CAT. TRY AGAIN LATER.")


@bot.command()
async def ping(ctx):
    latency_ms = round(bot.latency * 1000)
    await ctx.send(f"LATENCY: {latency_ms}MS")


@bot.command()
async def stats(ctx):
    total_murdered = sum(len(s) for s in murdered_users.values())
    await ctx.send(
        "**KILLER STATS**\n"
        f"Servers: {len(bot.guilds)}\n"
        f"Uptime: {format_uptime(time.time() - START_TIME)}\n"
        f"Latency: {round(bot.latency * 1000)}ms\n"
        f"Currently murdered (all servers): {total_murdered}"
    )


@bot.command()
async def credits(ctx):
    await ctx.send(
        "**CREDITS**\n"
        "Made by <@" + str(DEVELOPER_ID) + ">\n"
        "Hosted on Railway\n"
        "Greyscale service: some-random-api.com\n"
        "Cat service: thecatapi.com"
    )


@bot.tree.command(name="help", description="Shows all of Killer's commands")
async def help_slash(interaction: discord.Interaction):
    embed, _ = build_help_embed(0)
    view = HelpView(page=0)
    await interaction.response.send_message(embed=embed, view=view)


try:
    bot.run(TOKEN)
except Exception:
    print("=== BOT CRASHED ===")
    print(f"TOKEN present: {bool(TOKEN)}")
    traceback.print_exc()
    raise
