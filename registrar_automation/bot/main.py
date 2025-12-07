import asyncio
import logging
from aiogram import Bot, Dispatcher
from bot.config import BOT_TOKEN
from bot.handlers import common, registration

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    
    # Register Routers
    dp.include_router(common.router)
    dp.include_router(registration.router)
    
    print("🤖 Bot is starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
