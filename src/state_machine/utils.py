from abc import ABC, abstractmethod
from typing import Protocol, TypeVar

from aiogram.types import Message

from state_machine import ContextVars


def remove_context_vars(context: ContextVars, *keys: str) -> None:
    """Удаляет из словаря ContextVars перечисленные ключи."""
    for key in keys:
        try:
            del context[key]
        except KeyError:
            pass


T = TypeVar('T')

class Filterable(Protocol):
    def __call__(self, message: Message, *args, **kwargs) -> T: ...


class FilterDecorator(ABC):
    def __init__(self, *, have_self=True):
        self._have_self = have_self

    @abstractmethod
    def filter(self, message: Message) -> bool: ...

    async def __call__(self, func: Filterable):
        if self._have_self:
            async def wrapper(self_, message: Message, *args, **kwargs) -> T | None:
                if self.filter(message):
                    return await func(self_, message, *args, **kwargs)
        else:
            async def wrapper(message: Message, *args, **kwargs) -> T | None:
                if self.filter(message):
                    return await func(message, *args, **kwargs)
        return wrapper


class except_text(FilterDecorator):
    """Исключает вызов метода или функции с указанным текстом сообщения."""
    def __init__(self, *texts: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._texts = texts

    def filter(self, message: Message) -> bool:
        text = message.text
        return not any(t in text for t in self._texts)
