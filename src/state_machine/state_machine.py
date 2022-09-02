from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from typing import TypeAlias, Any, Iterable, Generator

from aiogram import Bot
from aiogram.types import Message, CallbackQuery

__all__ = [
    'State',
    'StateName',
    'StateMachine',
    'StateMachineStorage',
    'ContextVars',
    'Action',
    'SwitcherResult',
]

StateName: TypeAlias = str
SwitcherResult = StateName | None
ContextVars: TypeAlias = dict[str, Any]
Action = Message | CallbackQuery


class State(ABC):
    name: str = __name__

    async def on_enter(self, chat_id: int, bot: Bot, context: ContextVars) -> None:
        """Вызывается при переходе в это состояние."""
        ...

    async def on_exit(self, chat_id: int, bot: Bot, context: ContextVars) -> None:
        """Вызывается при выходе из этого состояния."""
        ...

    async def message_handler(self, message: Message, chat_id: int, bot: Bot, context: ContextVars) -> None:
        """
        Вызывается при получении сообщения от пользователя.
        Может изменить контекст пользователя.
        """
        ...

    async def callback_handler(self, query: CallbackQuery, chat_id: int, bot: Bot, context: ContextVars) -> None:
        """
        Вызывается при обратном вызове встроенной клавиатуры.
        Может изменить контекст пользователя.
        """
        ...

    async def after_action_switcher(self, action: Action, context: ContextVars) -> SwitcherResult:
        """
        Вызывается при получении сообщения или обратного вызова (после соответствующего обработчика).
        Может переключить состояние, вернув его название.
        """
        ...

    async def after_enter_switcher(self, context: ContextVars) -> SwitcherResult:
        """
        Вызывается при переходе в это состояние (после on_enter и до обработчиков).
        Может переключить состояние, вернув его название.
        """
        ...


class StateMachineStorage(ABC):
    @abstractmethod
    async def get_state(self, chat_id: int) -> str | None:
        """Получить имя состояния пользователя или None если пользователь не существует."""
        ...

    @abstractmethod
    async def set_state(self, chat_id: int, state_name: str) -> None:
        """Установить имя состояния пользователю. Пользователь будет добавлен, если не существовал."""
        ...

    @abstractmethod
    async def get_context(self, chat_id: int) -> ContextVars | None:
        """Получить контекстные переменные пользователя, если он существует."""
        ...

    @abstractmethod
    async def set_context(self, chat_id: int, context: ContextVars) -> None:
        """Установить контекстные переменные пользователя. Пользователь будет добавлен, если не существовал."""
        ...


def _make_states_dict(states: Iterable[State]) -> dict[str, State]:
    states_dict = {}
    for state in states:
        if state.name in states_dict:
            raise AssertionError(f'Несколько состояний имеют одно имя {state.name}.')
        states_dict[state.name] = state
    return states_dict


class StateMachine:
    def __init__(self, states: Iterable[State], default_state: State,
                 state_machine_storage: StateMachineStorage, bot: Bot):
        self._states = _make_states_dict(states)
        assert default_state.name in self._states, \
            f'Неизвестное состояние по умолчанию {default_state}.'
        self._default_state = default_state
        self._storage = state_machine_storage
        self._bot = bot

    async def _get_state(self, chat_id: int) -> State | None:
        """Получить текущее состояние по идентификатору чата."""
        state_name = await self._storage.get_state(chat_id)
        return self._states.get(state_name)

    async def _set_state(self, chat_id: int, state: State) -> None:
        """Установить состояние по идентификатору чата."""
        await self._storage.set_state(chat_id, state.name)

    @asynccontextmanager
    async def _context(self, user_id: int) -> Generator[ContextVars, None, None]:
        """Контекстный менеджер редактирования контекстных переменных пользователя."""
        context = await self._storage.get_context(user_id) or {}
        try:
            yield context
        finally:
            await self._storage.set_context(user_id, context)

    async def _switch_state(self, chat_id: int, current_state: State | None,
                            next_state: State, context: ContextVars) -> None:
        """Переключить состояние пользователя, вызвав все надлежащие обработчики."""
        if current_state is not None:
            await current_state.on_exit(chat_id, self._bot, context)
        await next_state.on_enter(chat_id, self._bot, context)
        await self._set_state(chat_id, next_state)
        next_state_name = await next_state.after_enter_switcher(context)
        while next_state_name is not None:
            current_state, next_state = next_state, self._states[next_state_name]
            await current_state.on_exit(chat_id, self._bot, context)
            await next_state.on_enter(chat_id, self._bot, context)
            await self._set_state(chat_id, next_state)
            next_state_name = await next_state.after_enter_switcher(context)

    async def handle_action(self, action: Action):
        """Обработать действие (сообщение или обратный вызов)."""
        chat_id = action.from_user.id
        async with self._context(chat_id) as context:
            # Получение текущего состояния
            current_state = await self._get_state(chat_id)
            if current_state is None:
                # Состояние пользователя не валидно
                await self._switch_state(chat_id, None, self._default_state, context)
                return
            # Вызов обработчиков
            match action:
                case Message() as message:
                    await current_state.message_handler(message, chat_id, self._bot, context)
                case CallbackQuery() as query:
                    await current_state.callback_handler(query, chat_id, self._bot, context)
            # Переключение состояния
            if next_state_name := await current_state.after_action_switcher(action, context):
                next_state = self._states[next_state_name]
                await self._switch_state(chat_id, current_state, next_state, context)
