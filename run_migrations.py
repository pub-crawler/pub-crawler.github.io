import asyncpg
from pub_crawler.database import database_setup
import asyncio
import os


async def run_migrations():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await database_setup(conn)
    finally:
        await conn.close()


asyncio.run(run_migrations())
