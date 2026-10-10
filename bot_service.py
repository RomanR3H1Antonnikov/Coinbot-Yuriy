#!/usr/bin/env python3
"""
Entry point for systemd: python bot_service.py
Runs aiogram long-polling bot.
"""
import asyncio
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from db.database import init_db
from bot.setup import bot, dp
from aiogram.types import BotCommand
from bot.handlers import router, BOT_COMMANDS
from utils.logger import setup_logger

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
setup_logger("root", os.path.join(BASE_DIR, "logs", "bot.log"))
logger = logging.getLogger(__name__)


async def main():
    init_db()
    dp.include_router(router)
    try:
        await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in BOT_COMMANDS])
    except Exception as e:
        logger.warning("Could not set bot command menu: %s", e)
    logger.info("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
