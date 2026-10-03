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

CATEGORY_ORDER = ["all", "moderation", "gambling", "fun", "info"]

COMMANDS_PER_PAGE = 7


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
        try:
            await interaction.response.edit_message(embed=embed, view=view)
        except discord.NotFound:
            await interaction.followup.send(
                "INTERACTION TIMEOUT — RUN `/help` AGAIN.",
                ephemeral=True,
            )
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
            await interaction.followup.send(
                "INTERACTION TIMEOUT — RUN `/help` AGAIN.",
                ephemeral=True,
            )
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
            await interaction.followup.send(
                "INTERACTION TIMEOUT — RUN `/help` AGAIN.",
                ephemeral=True,
            )
        except discord.HTTPException:
            pass


def tier_emoji(member) -> str:
    """Returns the appropriate tier emoji for a member."""
    if member is None:
        return TIER_VIAL

    # Dev or server owner or administrator
    if member.id == DEVELOPER_ID:
        return TIER_BARREL
    if member.guild and member.guild.owner_id == member.id:
        return TIER_BARREL
    perms = member.guild_permissions
    if perms.administrator:
        return TIER_BARREL

    # Decent mod-tier powers
    mod_perms = (
        perms.manage_messages
        or perms.manage_members
        or perms.manage_channels
        or perms.manage_roles
        or perms.manage_webhooks
        or perms.manage_guild
        or perms.kick_members
        or perms.ban_members
    )
    if mod_perms:
        return TIER_BOTTLE

    return TIER_VIAL


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


async def tier_reply(ctx, text):
    """Reply with the appropriate tier emoji appended to the text."""
    emoji = tier_emoji(ctx.author)
    await ctx.reply(f"{text} {emoji}")

async def ensure_jackpot_role(guild):
    role = discord.utils.get(guild.roles, name=JACKPOT_ROLE_NAME)
    if role is not None:
        return role
    try:
        role = await guild.create_role(
            name=JACKPOT_ROLE_NAME,
            color=JACKPOT_ROLE_COLOR,
            reason="JACKPOT role auto-created by Starlight",
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
        new_odds = current - 1
        if new_odds < 1:
            new_odds = 1
        roulette_odds[ctx.guild.id] = new_odds
        await tier_reply(ctx, f"💥 {ctx.author.mention} pulled the trigger... bang. You're dead.")
        await apply_murder(ctx, ctx.author)
    else:
        await tier_reply(ctx, f"{ctx.author.mention} pulled the trigger... click. You survived.")


@bot.command()
async def spin(ctx):
    new_odds = random.randint(1, 6)
    roulette_odds[ctx.guild.id] = new_odds
    await tier_reply(ctx, f"{ctx.author.mention} spun the cylinder.")


@bot.command()
async def loadbullet(ctx):
    current = roulette_odds.get(ctx.guild.id, 1)

    if current >= 5:
        roulette_odds[ctx.guild.id] = 5
        await tier_reply(ctx, f"{ctx.author.mention} tried to load a bullet... but the chamber is already at max.")
        return

    new_odds = current + 1
    roulette_odds[ctx.guild.id] = new_odds
    await tier_reply(ctx, f"{ctx.author.mention} loaded a bullet.")


@bot.command()
async def bulletsky(ctx):
    current = roulette_odds.get(ctx.guild.id, 1)

    if current <= 1:
        await tier_reply(ctx, f"{ctx.author.mention} shot at the sky... but there weren't any bullets to waste.")
        return

    new_odds = current - 1
    roulette_odds[ctx.guild.id] = new_odds
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
async def cat(ctx):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get("https://api.thecatapi.com/v1/images/search") as resp:
                if resp.status != 200:
                    await tier_reply(ctx, "Couldn't fetch a cat. Try again later.")
                    return
                data = await resp.json()
            cat_url = data[0]["url"]
            await tier_reply(ctx, cat_url)
        except Exception as e:
            print(f"Cat fetch failed: {e}")
            await tier_reply(ctx, "Couldn't fetch a cat. Try again later.")


@bot.command()
async def ping(ctx):
    latency_ms = round(bot.latency * 1000)
    await tier_reply(ctx, f"Latency: {latency_ms}ms")


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


try:
    bot.run(TOKEN)
except Exception:
    print("=== BOT CRASHED ===")
    print(f"TOKEN present: {bool(TOKEN)}")
    traceback.print_exc()
    raise
