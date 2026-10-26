from app.config import PROJECT_ROOT


BOT_NAME = "allsewpattern | Подбор выкроек"
BOT_DESCRIPTION = (
    "Выкройки разных брендов в одном каталоге. Находите модели по типу изделия, "
    "выбирайте подходящие варианты и переходите на сайт производителя.\n\n"
    "Нажмите «Старт», чтобы открыть каталог."
)
BOT_SHORT_DESCRIPTION = "Сервис по подбору выкроек. Разные бренды, удобный каталог и переход к производителю."
WELCOME_TEXT = (
    "allsewpattern\nСервис по подбору выкроек\n\n"
    "Ваша следующая идея начинается здесь.\n"
    "Собрали выкройки разных брендов, чтобы вам было проще найти свою модель.\n\n"
    "Откройте каталог: выбирайте изделия, сравнивайте модели и переходите на сайт производителя."
)
WELCOME_IMAGE = PROJECT_ROOT / "app" / "assets" / "welcome.jpg"
AVATAR_IMAGE = PROJECT_ROOT / "app" / "assets" / "avatar.jpg"


async def configure_bot() -> None:
    from aiogram import Bot
    from aiogram.types import BotCommand, FSInputFile, InputProfilePhotoStatic
    from app.config import load_settings

    async with Bot(load_settings().bot_token) as bot:
        for language in ("", "ru"):
            await bot.set_my_name(BOT_NAME, language_code=language)
            await bot.set_my_description(BOT_DESCRIPTION, language_code=language)
            await bot.set_my_short_description(BOT_SHORT_DESCRIPTION, language_code=language)
        await bot.set_my_commands([BotCommand(command="start", description="Открыть каталог выкроек")])
        await bot.set_my_profile_photo(InputProfilePhotoStatic(photo=FSInputFile(AVATAR_IMAGE)))
        print("Bot branding configured")


if __name__ == "__main__":
    import asyncio
    asyncio.run(configure_bot())
