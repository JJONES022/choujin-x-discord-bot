# Choujin X Discord Bot — Phase 1 scaffold

This is a **development scaffold**, not a complete anime intelligence monitor. It implements Discord DM opt-in, server channel selection via mentions, manga/anime toggles, SQLite persistence, and a five-minute editable chapter countdown for server channels. It does **not yet** implement web research, evidence verification, anime alerts, DM countdown updates, automatic chapter-date prediction, persistent button restoration, or automated welcome/onboarding on server join.

## Start locally

1. Create a Discord application at https://discord.com/developers/applications and add a bot. Enable **Message Content Intent** in Bot settings. Invite it using `bot` and `applications.commands` scopes, with permissions to View Channels, Send Messages, Read Message History, Embed Links, and use application commands. Do not grant Administrator.
2. `python -m venv .venv`; activate it (`.venv\\Scripts\\activate` on Windows, or `source .venv/bin/activate` on macOS/Linux).
3. `pip install -r requirements.txt`.
4. Copy `.env.example` to `.env`, add the bot token. Never commit `.env`.
5. `python -m bot.main`.
6. In the server use `/setup`, then mention the bot in the target channel. Toggle Manga and/or Anime. Members can run `/subscribe` to receive their personal DM setup buttons. `/chapter` displays the countdown.

**Important:** `EXPECTED_CHAPTER_AT` must be a timezone-aware ISO 8601 timestamp, e.g. `2026-11-20T22:00:00-05:00`, and is only an illustrative example. Leave it blank until a real source or documented estimate is configured. Discord timestamps localize for viewers automatically. The bot marks all manually configured dates as estimated.

## Production notes

- Slash commands are synced on startup for this single-instance prototype. For production, use a separate deployment-time sync to avoid unnecessary calls.
- Button views have a five-minute timeout and do not survive restarts. Add persistent views and user-specific interaction guards before deployment.
- The setup buttons are restricted to the user who opened the menu; production should also add persistent views and a better channel-management workflow.
- The countdown currently sends a message on enabling manga, and edits it at most every five minutes. It does not yet notify DMs about new chapters.
- Multi-server deployment should use PostgreSQL if running more than one worker. SQLite is fine for a single process.
- Only send anime alerts when the verification pipeline has independently corroborated claims; never automatically notify from a keyword match alone.
- Follow platform terms, robots directives, and rate limits. Public metadata and domain records are clues, not proof of production.
