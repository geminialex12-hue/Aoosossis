import asyncio
import os
import httpx

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()


class Registration(StatesGroup):
    nickname = State()
    game_id = State()


def start_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Пользовательское соглашение", url=f"{WEBAPP_URL}/terms")],
        [InlineKeyboardButton(text="✅ Согласен", callback_data="terms_accept")],
    ])


def app_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть STANDKNIFE", web_app={"url": WEBAPP_URL})]
    ])


def menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 ИГРАТЬ", web_app={"url": WEBAPP_URL})],
        [
            InlineKeyboardButton(text="👥 НАПАРНИКИ", web_app={"url": WEBAPP_URL}),
            InlineKeyboardButton(text="👤 ПРОФИЛЬ", web_app={"url": WEBAPP_URL}),
        ],
        [
            InlineKeyboardButton(text="📊 СТАТИСТИКА", web_app={"url": WEBAPP_URL}),
            InlineKeyboardButton(text="🔎 ПОИСК", web_app={"url": WEBAPP_URL}),
        ],
        [
            InlineKeyboardButton(text="⚙️ НАСТРОЙКИ", web_app={"url": WEBAPP_URL}),
            InlineKeyboardButton(text="◆ PREMIUM", web_app={"url": WEBAPP_URL}),
        ],
    ])


async def backend_user(message: Message):
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.post(
            f"{BACKEND_URL}/api/bot/user",
            headers={"X-Bot-Token": BOT_TOKEN},
            json={
                "telegram_id": message.from_user.id,
                "username": message.from_user.username,
                "first_name": message.from_user.first_name,
            },
        )
        response.raise_for_status()
        return response.json()


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()

    try:
        result = await backend_user(message)
    except Exception:
        await message.answer("⚠️ Сервер временно недоступен. Попробуйте ещё раз.")
        return

    if result.get("registered"):
        await message.answer(
            "🎮 <b>STANDKNIFE</b>\n\nДобро пожаловать обратно!",
            reply_markup=menu_keyboard(),
            parse_mode="HTML",
        )
        return

    await message.answer(
        "🎮 <b>STANDKNIFE</b>\n\n"
        "Перед использованием платформы примите пользовательское соглашение.",
        reply_markup=start_keyboard(),
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "terms_accept")
async def terms_accept(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Registration.nickname)

    await callback.message.edit_text(
        "✅ Соглашение принято.\n\nВведите игровой ник StandKnife:"
    )
    await callback.answer()


@dp.message(Registration.nickname)
async def nickname(message: Message, state: FSMContext):
    value = (message.text or "").strip()

    if not 2 <= len(value) <= 32:
        await message.answer("❌ Ник должен содержать от 2 до 32 символов.")
        return

    await state.update_data(nickname=value)
    await state.set_state(Registration.game_id)
    await message.answer("🆔 Теперь отправьте ваш StandKnife ID:")


@dp.message(Registration.game_id)
async def game_id(message: Message, state: FSMContext):
    value = (message.text or "").strip()

    if not 1 <= len(value) <= 64:
        await message.answer("❌ Некорректный ID.")
        return

    data = await state.get_data()

    async with httpx.AsyncClient(timeout=8) as client:
        try:
            response = await client.post(
                f"{BACKEND_URL}/api/bot/register",
                headers={"X-Bot-Token": BOT_TOKEN},
                json={
                    "telegram_id": message.from_user.id,
                    "nickname": data["nickname"],
                    "game_id": value,
                },
            )
            response.raise_for_status()
        except Exception:
            await message.answer("⚠️ Не удалось сохранить профиль. Попробуйте ещё раз.")
            return

    await state.clear()

    await message.answer(
        "🎉 <b>Регистрация завершена!</b>\n\n"
        f"🎮 Ник: <b>{data['nickname']}</b>\n"
        f"🆔 ID: <code>{value}</code>\n\n"
        "Откройте платформу:",
        reply_markup=app_keyboard(),
        parse_mode="HTML",
    )


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not configured")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
