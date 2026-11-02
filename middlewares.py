import asyncio
from typing import Any, Callable, Dict, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message


class MediaGroupMiddleware(BaseMiddleware):
    def __init__(self, latency: float = 0.6):
        self.latency = latency
        self.albums: Dict[str, list[Message]] = {}

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        if not event.media_group_id:
            return await handler(event, data)

        total_group = self.albums.setdefault(event.media_group_id, [])
        total_group.append(event)

        # Ждем, пока придут все элементы альбома
        await asyncio.sleep(self.latency)

        # Выполняем хэндлер только для последнего пришедшего сообщения пачки
        if event.message_id != total_group[-1].message_id:
            return

        data["album"] = total_group
        del self.albums[event.media_group_id]
        return await handler(event, data)