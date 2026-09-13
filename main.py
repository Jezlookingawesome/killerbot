import discord
from discord.ext import commands
from discord import Webhook
import aiohttp
from io import BytesIO
import os
import random
import traceback
from urllib.parse import quote

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")

murdered_users = {}

DEVELOPER_ID = 1478853756874395762
JACKPOT_ROLE_NAME = "JACKPOT☘️"
JACKPOT_ROLE_COLOR = discord.Color.from_rgb(0, 255, 0)


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


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
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
        await ctx.send("YOU NEED TO PING SOMEONE TO MURDER. USAGE: `!murder @user`")
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
        await ctx.send(f"{member.mention} ISN'T MURDERED, DUMBASS.")
        return

    murdered_set.discard(member.id)
    await ctx.send(f"{member.mention} HAS BEEN REVIVED💖")


@bot.command()
async def murdered(ctx):
    ids = murdered_users.get(ctx.guild.id, set())
    if not ids:
        await ctx.send("NO VICTIMS YET👀")
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


@bot.command(name="help")
async def help_command(ctx):
    await ctx.send(
        "**Prefix: !**\n\n"
        "**Commands**\n"
        "murder @user — jeff the kills the user🔪🔪\n"
        "unmurder @user — revives them💖 (no mention = revives yourself)\n"
        "murdered — lists everyone currently murdered\n"
        "gamble — rolls a d20\n"
        "jgamble — same as gamble, but if you roll below 10 you DIE\n"
        "highstakes — rolls a d1000, roll 777 to win the JACKPOT☘️ role\n"
        "help — shows this list"
    )


try:
    bot.run(TOKEN)
except Exception:
    print("=== BOT CRASHED ===")
    print(f"TOKEN present: {bool(TOKEN)}")
    traceback.print_exc()
    raise
