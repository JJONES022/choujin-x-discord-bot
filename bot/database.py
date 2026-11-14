import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS dm_subscriptions (
    user_id INTEGER PRIMARY KEY,
    manga INTEGER NOT NULL DEFAULT 0,
    anime INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS server_subscriptions (
    guild_id INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    manga INTEGER NOT NULL DEFAULT 0,
    anime INTEGER NOT NULL DEFAULT 0,
    countdown_message_id INTEGER
);
CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL,
    confidence TEXT NOT NULL, first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deliveries (
    finding_id TEXT NOT NULL, destination TEXT NOT NULL,
    PRIMARY KEY(finding_id, destination)
);
"""


class Store:
    def __init__(self, path):
        self.path = path

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(SCHEMA)
            columns = await (await db.execute("PRAGMA table_info(server_subscriptions)")).fetchall()
            if "role_panel_message_id" not in {col[1] for col in columns}:
                await db.execute("ALTER TABLE server_subscriptions ADD COLUMN role_panel_message_id INTEGER")
            await db.execute("CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            await db.commit()

    async def last_jp_release(self):
        from datetime import datetime
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute(
                "SELECT value FROM bot_state WHERE key='last_jp_release_at'"
            )).fetchone()
            return datetime.fromisoformat(row[0]) if row else None

    async def set_last_jp_release(self, value):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO bot_state(key,value) VALUES('last_jp_release_at',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (value.isoformat(),)
            )
            await db.commit()

    async def publisher_baseline(self):
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute(
                "SELECT id FROM findings WHERE confidence='official_publisher' ORDER BY first_seen ASC LIMIT 1"
            )).fetchone()
            return row[0] if row else None

    async def latest_publisher_finding(self):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM findings WHERE confidence='official_publisher' ORDER BY first_seen DESC LIMIT 1"
            )).fetchone()
            return dict(row) if row else None

    async def add_publisher_finding(self, finding_id, title, url):
        from datetime import datetime, timezone
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO findings(id,title,url,confidence,first_seen) VALUES(?,?,?,?,?)",
                (finding_id, title, url, 'official_publisher', datetime.now(timezone.utc).isoformat())
            )
            await db.commit()

    async def is_delivered(self, finding_id, destination):
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute(
                "SELECT 1 FROM deliveries WHERE finding_id=? AND destination=?",
                (finding_id, destination)
            )).fetchone()
            return row is not None

    async def mark_delivered(self, finding_id, destination):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO deliveries(finding_id,destination) VALUES(?,?)",
                (finding_id, destination)
            )
            await db.commit()

    async def manga_dm_users(self):
        async with aiosqlite.connect(self.path) as db:
            rows = await (await db.execute(
                "SELECT user_id FROM dm_subscriptions WHERE manga=1"
            )).fetchall()
            return [row[0] for row in rows]

    async def anime_dm_users(self):
        async with aiosqlite.connect(self.path) as db:
            rows = await (await db.execute(
                "SELECT user_id FROM dm_subscriptions WHERE anime=1"
            )).fetchall()
            return [row[0] for row in rows]

    async def get_dm(self, user_id):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT manga, anime FROM dm_subscriptions WHERE user_id=?", (user_id,)
            )).fetchone()
            return dict(row) if row else None

    async def set_dm(self, user_id, manga, anime):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO dm_subscriptions(user_id,manga,anime) VALUES(?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET manga=excluded.manga,anime=excluded.anime
            """, (user_id, int(manga), int(anime)))
            await db.commit()

    async def get_server(self, guild_id, channel_id=None):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM server_subscriptions WHERE guild_id=?", (guild_id,)
            )).fetchone()
            if not row or (channel_id is not None and row["channel_id"] != channel_id):
                return None
            return dict(row)

    async def set_server(self, guild_id, channel_id, manga, anime):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO server_subscriptions(guild_id,channel_id,manga,anime)
                VALUES(?,?,?,?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    countdown_message_id=CASE WHEN channel_id=excluded.channel_id
                        THEN countdown_message_id ELSE NULL END,
                    role_panel_message_id=CASE WHEN channel_id=excluded.channel_id
                        THEN role_panel_message_id ELSE NULL END,
                    channel_id=excluded.channel_id,
                    manga=excluded.manga, anime=excluded.anime
            """, (guild_id, channel_id, int(manga), int(anime)))
            await db.commit()

    async def set_countdown_message(self, guild_id, message_id):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE server_subscriptions SET countdown_message_id=? WHERE guild_id=?",
                (message_id, guild_id)
            )
            await db.commit()

    async def set_role_panel_message(self, guild_id, message_id):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE server_subscriptions SET role_panel_message_id=? WHERE guild_id=?",
                (message_id, guild_id)
            )
            await db.commit()

    async def servers(self):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            rows = await (await db.execute("SELECT * FROM server_subscriptions")).fetchall()
            return [dict(row) for row in rows]

    async def get_state(self, key):
        async with aiosqlite.connect(self.path) as db:
            row = await (await db.execute('SELECT value FROM bot_state WHERE key=?', (key,))).fetchone()
            return row[0] if row else None

    async def set_state(self, key, value):
        async with aiosqlite.connect(self.path) as db:
            await db.execute('INSERT INTO bot_state(key,value) VALUES(?,?) '
                             'ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))
            await db.commit()

    async def last_en_release(self):
        from datetime import datetime
        value = await self.get_state('last_en_release_at')
        return datetime.fromisoformat(value) if value else None

    async def set_last_en_release(self, value, chapter, hour_verified=False):
        await self.set_state('last_en_release_at', value.isoformat())
        await self.set_state('last_en_chapter', chapter)
        await self.set_state('last_en_hour_verified', '1' if hour_verified else '0')
