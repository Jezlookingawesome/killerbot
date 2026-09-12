import discord
from discord.ext import commands
from discord import Webhook
import aiohttp
from PIL import Image, ImageOps
from io import BytesIO
import os

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

murdered = {}
grey_cache = {}


async def grey_avatar(user: discord.User):
    if user.id in grey_cache:
        return discord.File(BytesIO(grey_cache[user.id]), filename="grey.png")

    async with aiohttp.ClientSession() as session:
        async with session.get(user.display_avatar.with_size(256).url) as resp:
            data = await resp.read()

    img = Image.open(BytesIO(data)).convert("RGBA")
    grey = ImageOps.grayscale(img).convert("RGBA")
    overlay = Image.new("RGBA", grey.size, (0, 0, 0, 80))
    grey = Image.alpha_composite(grey, overlay)

    buf = BytesIO()
    grey.save(buf, format="PNG")
    grey_cache[user.id] = buf.getvalue()
    return discord.File(BytesIO(buf.getvalue()), filename="grey.png")


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

    muted = murdered.get(message.guild.id, set())
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

    avatar_file = await grey_avatar(message.author)

    async with aiohttp.ClientSession() as session:
        wh = Webhook.from_url(webhook.url, session=session)
        await wh.send(
            content="\u200b",
            username=message.author.display_name,
            avatar_url="attachment://grey.png",
            file=avatar_file,
        )


@bot.command()
@commands.has_permissions(manage_messages=True)
async def murder(ctx, member: discord.Member):
    murdered.setdefault(ctx.guild.id, set()).add(member.id)
    grey_cache.pop(member.id, None)
    await ctx.send(f"{member.mention} has been murdered.")


@bot.command()
@commands.has_permissions(manage_messages=True)
async def unmurder(ctx, member: discord.Member):
    murdered.setdefault(ctx.guild.id, set()).discard(member.id)
    grey_cache.pop(member.id, None)
    await ctx.send(f"{member.mention} has been revived.")


@bot.command()
async def murdered(ctx):
    ids = murdered.get(ctx.guild.id, set())
    if not ids:
        await ctx.send("No one is murdered.")
        return
    mentions = ", ".join(f"<@{i}>" for i in ids)
    await ctx.send(f"Currently murdered: {mentions}")


bot.run(TOKEN)
