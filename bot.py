import asyncio
import logging

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

TELEGRAM_TOKEN = "8840188717:AAGH_X2dXK05EI_mpXTM6kA6v6gj38uvX6s"
API_KEY = "sk-oW2PxiPP8Mi7MwGGaNkoZrqIAdoE2mV1JckKyMNV6p3v3AbT"
API_URL = "https://agentrouter.org/v1/chat/completions"
MODEL = "gpt-6-astra"
SYSTEM_PROMPT = "You are a helpful assistant. Reply in the language of the user."
MAX_HISTORY = 20
REQUEST_TIMEOUT = 120

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=None))
dp = Dispatcher()

histories: dict[int, list[dict]] = {}
locks: dict[int, asyncio.Lock] = {}


def get_lock(user_id: int) -> asyncio.Lock:
    if user_id not in locks:
        locks[user_id] = asyncio.Lock()
    return locks[user_id]


async def ask_model(messages: list[dict]) -> str:
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"model": MODEL, "messages": messages}
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(API_URL, json=payload, headers=headers) as resp:
            text = await resp.text()
            if resp.status != 200:
                raise RuntimeError(f"API {resp.status}: {text[:500]}")
            data = await resp.json(content_type=None)
    return data["choices"][0]["message"]["content"].strip()


def split_text(text: str, limit: int = 4000) -> list[str]:
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts


async def keep_typing(chat_id: int, stop: asyncio.Event):
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id, ChatAction.TYPING)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=4)
        except asyncio.TimeoutError:
            pass


@dp.message(CommandStart())
async def cmd_start(message: Message):
    histories[message.from_user.id] = []
    await message.answer(
        "Привет! Я чат-бот на модели gpt-6-astra. Напиши мне что-нибудь.\n"
        "/reset — очистить историю диалога."
    )


@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    histories[message.from_user.id] = []
    await message.answer("История диалога очищена.")


@dp.message(F.text)
async def on_text(message: Message):
    user_id = message.from_user.id
    async with get_lock(user_id):
        history = histories.setdefault(user_id, [])
        history.append({"role": "user", "content": message.text})
        if len(history) > MAX_HISTORY:
            del history[: len(history) - MAX_HISTORY]

        stop = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(message.chat.id, stop))
        try:
            reply = await ask_model(
                [{"role": "system", "content": SYSTEM_PROMPT}] + history
            )
        except Exception as e:
            logging.exception("model error")
            history.pop()
            await message.answer(f"Ошибка: {e}")
            return
        finally:
            stop.set()
            await typing_task

        history.append({"role": "assistant", "content": reply})
        for chunk in split_text(reply or "(пустой ответ)"):
            await message.answer(chunk)


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
