# 🔪 Killer

> A Discord bot that jeff the kills people. (Also has other fun stuff)

Killer is a joke/meme Discord bot. When someone gets "murdered," their profile picture turns greyscale and every message they send is replaced with a blank message under their name. They stay that way until someone revives them.

It also has gambling, a cat command, and other nonsense.

---

## Commands

**Murder**
- `!murder @user` — jeff the kills the user
- `!unmurder @user` — revives them (no mention = revives yourself)
- `!murdered` — lists everyone currently murdered

**Gambling**
- `!gamble` — rolls a d20
- `!jgamble` — same as gamble, but if you roll below 10 you DIE
- `!highstakes` — rolls a d1000
- `!roulette` — 1/6 chance of getting murdered

**Fun**
- `!cat` — posts a random cat image

**Info**
- `!ping` — shows the bot's latency
- `!stats` — shows bot stats
- `!credits` — shows who made the bot
- `/help` — paginated command list (slash command)

---

## Self-hosting

### Prerequisites

- A Discord bot application ([Developer Portal](https://discord.com/developers/applications))
- A host that runs Python (Railway, Render, Fly.io, etc.)
- The bot needs these **Privileged Gateway Intents** enabled:
  - ✅ Message Content Intent
  - ✅ Server Members Intent
- And these **permissions** on the server:
  - Manage Messages
  - Manage Webhooks
  - Manage Roles (for `!highstakes`' role grant)
  - Send Messages, View Channels, Attach Files, Read Message History

### Environment variables

| Variable | Description |
|---|---|
| `TOKEN` | Your bot's token from the Discord Developer Portal |

### Deploy

1. Fork or clone this repo
2. Create a new project on your host and connect the repo
3. Set the `TOKEN` environment variable
4. Deploy — the bot will auto-start

On Railway: **New Project → Deploy from GitHub repo → select repo → add `TOKEN` variable → deploy.**

---

## How the "murder" effect works

When a user is murdered:

1. Their user ID is added to an in-memory `murdered_users` set (per server)
2. On every message they send, the bot:
   - Deletes the original message
   - Reposts it via a webhook using their display name and a **greyscaled version of their profile picture**
   - Uses a zero-width space as the message content, so it looks blank

The greyscale pfp is fetched from [some-random-api.com](https://some-random-api.com).

**Note:** the murdered list lives in memory. Restarting the bot clears everyone's murder state. (Persistent storage would need a database — not implemented.)

---

## Credits

- Made by **jezlookingawesome**
- Hosted on Railway
- Greyscale service: [some-random-api.com](https://some-random-api.com)
- Cat service: [thecatapi.com](https://thecatapi.com)

---

## License

literally just do whatever you want with this.

---

## tarnisheds

![demo](https://klipy.com/gifs/the-battle-bricks-tarnished-battler)

![demo](https://klipy.com/gifs/the-battle-bricks-tarnished-trowel)

![demo](https://klipy.com/gifs/tarnished-sword)

![demo](https://klipy.com/gifs/tarnished-destruction)
