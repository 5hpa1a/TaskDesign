import asyncio
from typing import Any, Callable, Dict, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message


class MediaGroupMiddleware(BaseMiddleware):
    """
    Корректно собирает все элементы медиагруппы (фото и документы до 10 шт.)
    с помощью единого debounce-таймера, исключая гонку состояний при одновременной отправке.
    """
    def __init__(self, latency: float = 0.8):
        self.latency = latency
        self.albums: Dict[str, list[Message]] = {}
        self.timers: Dict[str, asyncio.Task] = {}

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        if not event.media_group_id:
            return await handler(event, data)

        mg_id = event.media_group_id
        self.albums.setdefault(mg_id, []).append(event)

        # Сбрасываем предыдущий таймер, если пришло следующее сообщение из той же пачки
        existing_timer = self.timers.get(mg_id)
        if existing_timer and not existing_timer.done():
            existing_timer.cancel()

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()

        async def _debounce():
            try:
                await asyncio.sleep(self.latency)
                if not future.done():
                    future.set_result(True)
            except asyncio.CancelledError:
                if not future.done():
                    future.set_result(False)

        self.timers[mg_id] = asyncio.create_task(_debounce())
        is_last = await future

        if not is_last:
            return

        # Сортируем сообщения строго по message_id, чтобы сохранить порядок
        album = sorted(self.albums.pop(mg_id, []), key=lambda m: m.message_id)
        self.timers.pop(mg_id, None)

        data["album"] = album
        return await handler(event, data)