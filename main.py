import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiohttp import web

import config
import database as db
from handlers import router, restore_active_dialogs_for_all
from middlewares import MediaGroupMiddleware
from scheduler import setup_scheduler
from webapp import create_webapp_app


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )

    await db.init_db()

    session = AiohttpSession(timeout=60.0)
    bot = Bot(
        token=config.BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    
    dp = Dispatcher()
    dp.message.middleware(MediaGroupMiddleware(latency=0.8))
    dp.include_router(router)

    scheduler = setup_scheduler(bot)
    scheduler.start()

    app = create_webapp_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.WEBAPP_HOST, config.WEBAPP_PORT)
    await site.start()
    logging.info(f"Веб-сервер Mini App запущен на http://{config.WEBAPP_HOST}:{config.WEBAPP_PORT}")

    logging.info("Бот успешно запущен! Восстанавливаем активные диалоговые окна...")
    await restore_active_dialogs_for_all(bot)
    try:
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        scheduler.shutdown()
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())