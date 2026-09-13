import discord
from discord.ext import commands
from discord import Webhook
import aiohttp
from io import BytesIO
import os
import traceback
from urllib.parse import quote

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

murdered_users = {}


def grey_url(user: discord.User) -> str:
    avatar = str(user.display_avatar.with_size(256).url)
    return f"https://some-random-api.com/canvas/greyscale?avatar={quote(avatar, safe='')}"


async def fetch_grey_image(user: discord.User) -> discord.File | None:
    """Download the greyscaled avatar as a file."""
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


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


@bot.event
async def on_message(message: discord.Message):
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
async def murder(ctx, member: discord.Member):
    murdered_users.setdefault(ctx.guild.id, set()).add(member.id)
    await ctx.send(f"{member.mention} has been jeff the killed🔪🔪")

    image = await fetch_grey_image(member)
    if image:
        await ctx.send(file=image)
    else:
        await ctx.send("(couldn't fetch the greyscale pfp)")


@bot.command()
@commands.has_permissions(manage_messages=True)
async def unmurder(ctx, member: discord.Member):
    murdered_users.setdefault(ctx.guild.id, set()).discard(member.id)
    await ctx.send(f"{member.mention} has been revived💖")


@bot.command()
async def murdered(ctx):
    ids = murdered_users.get(ctx.guild.id, set())
    if not ids:
        await ctx.send("No one is murdered.")
        return
    mentions = ", ".join(f"<@{i}>" for i in ids)
    await ctx.send(f"Currently murdered: {mentions}")


@bot.command()
async def help(ctx):
    await ctx.send(
        "**Commands**\n"
        "`!murder @user` — jeff the kills them🔪🔪 (greys their pfp + blanks their messages)\n"
        "`!unmurder @user` — revives them💖\n"
        "`!murdered` — lists everyone currently murdered\n"
        "`!help` — shows this list"
    )


try:
    bot.run(TOKEN)
except Exception:
    print("=== BOT CRASHED ===")
    print(f"TOKEN present: {bool(TOKEN)}")
    traceback.print_exc()
    raise
