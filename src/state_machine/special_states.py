from abc import ABC, abstractmethod
from typing import Optional, Sequence, final, Any, TypeVar

from aiogram import Bot
from aiogram.types import Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from .state_machine import State, StateName, Action, ContextVars
from .utils import remove_context_vars

Keyboard = ReplyKeyboardMarkup | ReplyKeyboardRemove


class RenderedViewOnEnter(State, ABC):
    @abstractmethod
    async def render_text(self, chat_id: int, context: ContextVars) -> str: ...

    @abstractmethod
    async def render_keyboard(self, chat_id: int, context: ContextVars) -> Keyboard: ...

    @final
    async def send_view(self, chat_id: int, bot: Bot, context: ContextVars) -> None:
        text = await self.render_text(chat_id, context)
        keyboard = await self.render_keyboard(chat_id, context)
        await bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode='html')

    async def on_enter(self, chat_id: int, bot: Bot, context: ContextVars) -> None:
        await self.send_view(chat_id, bot, context)


class StaticViewOnEnter(RenderedViewOnEnter, ABC):
    @property
    @abstractmethod
    def text(self) -> str: ...

    @property
    @abstractmethod
    def keyboard(self) -> Keyboard: ...

    @final
    async def render_text(self, chat_id: int, context: ContextVars) -> str:
        return self.text

    @final
    async def render_keyboard(self, chat_id: int, context: ContextVars) -> Keyboard:
        return self.keyboard


ValidatorReturnType = TypeVar('ValidatorReturnType')

class ValidateOnMessage(State, ABC):
    @abstractmethod
    def validator(self, message: Message) -> ValidatorReturnType | None:
        ...

    async def on_correct(self, result: ValidatorReturnType, chat_id: int, bot: Bot, context: ContextVars) -> None:
        ...

    async def on_incorrect(self, message: Message, chat_id: int, bot: Bot, context: ContextVars) -> None:
        await bot.send_message(chat_id, 'Недопустимый ввод!')

    @final
    async def validate(self, message: Message, chat_id: int, bot: Bot, context: ContextVars) -> None:
        if (value := self.validator(message)) is not None:
            await self.on_correct(value, chat_id, bot, context)
        else:
            await self.on_incorrect(message, chat_id, bot, context)

    async def message_handler(self, message: Message, chat_id: int, bot: Bot, context: ContextVars) -> None:
        return await self.validate(message, chat_id, bot, context)


class ChoiceByMessage(ValidateOnMessage, ABC):
    """
    Обработка выбора по тексту сообщения. Атрибут options – варианты выбора.
    Если текст – это один из вариантов, то вызовется on_correct, иначе – on_incorrect.
    """
    @property
    @abstractmethod
    def options(self) -> Sequence[str]: ...

    @final
    def validator(self, message: Message) -> Any | None:
        if message.text in self.options:
            return message.text


class SwitchStateByMessage(ChoiceByMessage, ABC):
    """
    Переключает состояние в соответствии с текстом получаемого сообщения.
    Атрибут options_switcher – словарь, где ключ – текст сообщения, значение – название состояния.
    """
    @property
    @abstractmethod
    def options_switcher(self) -> dict[str, StateName]: ...

    @property
    def options(self):
        return self.options_switcher.keys()

    @final
    async def after_action_switcher(self, action: Optional[Action], context: ContextVars) -> Optional[StateName]:
        if isinstance(action, Message):
            if state_name := self.options_switcher.get(action.text):
                return state_name


class ClearVarsOnExit(State, ABC):
    """Удаляет переменные контекста, перечисленные в атрибуте clearing_vars."""
    @property
    @abstractmethod
    def clearing_vars(self) -> Sequence[str]: ...

    async def on_exit(self, chat_id: int, bot: Bot, context: ContextVars) -> None:
        remove_context_vars(context, *self.clearing_vars)
