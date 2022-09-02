import asyncio
from abc import ABC, abstractmethod
from datetime import date as Date, datetime as Datetime, timedelta
from dataclasses import dataclass
from typing import TypeAlias

from PIL import Image
from aiogram import md, Bot
from aiogram.types import Message, CallbackQuery

from bot_utils import make_simple_keyboard, make_simple_inline_keyboard
from state_machine import Action, ContextVars, StateName, SwitcherResult, State
from state_machine.special_states import (
    StaticViewOnEnter, SwitchStateByMessage, Keyboard,
    ClearVarsOnExit, ValidateOnMessage, RenderedViewOnEnter,
)
from state_machine.utils import remove_context_vars


UserId: TypeAlias = int
Descriptor: TypeAlias = list[float]
UserSearchQuery: TypeAlias = dict[str, str]


@dataclass
class UserInfo:
    id: int
    surname: str
    name: str
    patronymic: str
    position: str

    @property
    def full_name(self):
        return f'{self.surname} {self.name} {self.patronymic}'


@dataclass
class RoomInfo:
    id: int
    name: str


@dataclass
class VisitInfo:
    datetime: Datetime
    user_id: int


class MainNodeConnection(ABC):
    @abstractmethod
    async def calculate_descriptor(self, image: Image.Image) -> Descriptor | None: ...

    @abstractmethod
    async def create_user(self, surname: str, name: str, patronymic: str, position: str) -> int: ...

    @abstractmethod
    async def update_user(self, user_id: int, surname: str, name: str, patronymic: str, position: str) -> None: ...

    @abstractmethod
    async def update_face_descriptor(self, user_id: int, descriptor: list[float]): ...

    @abstractmethod
    async def get_user_info(self, user_id: int) -> UserInfo: ...

    @abstractmethod
    async def search_users(self, query: UserSearchQuery, limit: int = None, offset: int = None) -> list[UserInfo]: ...

    @abstractmethod
    async def get_available_user_positions(self) -> list[str]: ...

    @abstractmethod
    async def get_controlling_rooms(self, manager_id: int) -> list[RoomInfo]: ...

    @abstractmethod
    async def get_room_info(self, room_id: int) -> RoomInfo: ...

    @abstractmethod
    async def get_visits(self, room_id: int, date: Date) -> list[VisitInfo]: ...

    @abstractmethod
    async def creat_open_door_task(self, manager_id: int, room_id: int) -> None: ...

    @abstractmethod
    async def configure_access(self, room_id: int, user_id: int, accessed: bool): ...

    @abstractmethod
    async def get_accessed_users(self, room_id: int) -> list[UserInfo]: ...


class MainMenu(StaticViewOnEnter, SwitchStateByMessage):
    """Главное меню."""
    text = 'Выберите раздел:'
    options_switcher = {
        'Помещения': 'RoomsList',
        'Пользователи': 'UsersMenu',
    }
    keyboard = make_simple_keyboard(*options_switcher.keys())


class UsersMenu(StaticViewOnEnter, SwitchStateByMessage, ClearVarsOnExit):
    """Меню «Пользователи»."""
    text = md.text('Раздел', md.hbold('Пользователи'))
    options_switcher = {
        'Поиск': 'WaitUserSearchQuery',
        'Добавить пользователя': 'WaitUserFullName',
        'Назад': 'MainMenu',
    }
    keyboard = make_simple_keyboard(*options_switcher.keys())
    clearing_vars = ['full_name', 'position', 'descriptor', 'user_id']


class WaitUserFullName(StaticViewOnEnter, ValidateOnMessage):
    """Ожидание ввода ФИО нового пользователя."""
    text = md.text(
        'Введите фамилию, имя и отчество нового пользователя в следующем формате:',
        '✔ допустимые символы: А-Я, а-я, A-Z, a-z, -;',
        '✔ каждое слово должно начинаться с заглавной буквы;',
        '✔ фамилией считается 1-е слово, именем – 2-е, отчеством – 3-е.',
        'Пример: Маркер Виктор Андреевич',
        sep='\n'
    )
    keyboard = make_simple_keyboard('Отмена')

    def validator(self, message: Message) -> str | None:
        full_name = message.text
        words = full_name.split()
        are_words_capitalized = all(w.replace('-', '').isalpha() and w[0].isupper() for w in words)
        if len(words) >= 3 and are_words_capitalized:
            return full_name

    async def on_correct(self, full_name: str, _, __, context: ContextVars) -> None:
        context['full_name'] = full_name

    async def on_incorrect(self, message: Message, chat_id: int, bot: Bot, __) -> None:
        if message.text != 'Отмена':
            await bot.send_message(chat_id, 'Неверный формат ФИО!')

    async def after_action_switcher(self, action: Action, context: ContextVars) -> SwitcherResult:
        if isinstance(action, Message) and action.text == 'Отмена':
            return 'UsersMenu' if 'user_id' not in context else 'UserPage'
        if 'full_name' in context:
            return 'WaitUserPosition' if 'user_id' not in context else 'UpdateUser'


class WaitUserPosition(RenderedViewOnEnter, ValidateOnMessage):
    """Ожидание выбора должности нового пользователя."""
    def __init__(self, main_node_connection: MainNodeConnection):
        self._conn = main_node_connection
        self._options = ['Отмена']

    async def render_keyboard(self, _, __) -> Keyboard:
        positions = await self._conn.get_available_user_positions()
        self._options = positions + ['Отмена']
        return make_simple_keyboard(*self._options)

    async def render_text(self, _, __) -> str:
        return 'Выберите должность:'

    def validator(self, message: Message) -> str | None:
        if message.text in self._options:
            return message.text

    async def on_correct(self, option: str, _, __, context: ContextVars) -> None:
        if option != 'Отмена':
            context['position'] = option

    async def after_action_switcher(self, action: Action, context: ContextVars) -> SwitcherResult:
        if isinstance(action, Message) and action.text == 'Отмена':
            return 'UsersMenu' if 'user_id' not in context else 'UserPage'
        if 'position' in context:
            return 'WaitUserFacePhoto' if 'user_id' not in context else 'UpdateUser'


class WaitUserFacePhoto(StaticViewOnEnter):
    """Ожидание ввода фотографии пользователя."""
    text = md.text(
        'Пришлите изображение с лицом пользователя для получения модели:',
        f'✔ лицо пользователя должно быть {md.hbold("самым крупным")} на изображении;',
        f'✔ ширина и высота изображения должны иметь длину {md.hbold("не меньше 600 px")};',
        'Размытые и смазанные фотографии ведут к ухудшению распознавания.',
        sep='\n',
    )
    keyboard = make_simple_keyboard('Отмена')

    def __init__(self, main_node_connection: MainNodeConnection):
        self._conn = main_node_connection

    async def message_handler(self, message: Message, chat_id: int, bot: Bot, context: ContextVars) -> None:
        match message:
            case Message(text='Отмена'):
                return
            case Message(photo=[*_, photo]):
                # Загрузка изображения из Telegram
                file_id = photo.file_id
                image_stream = await bot.download_file_by_id(file_id)
                image = Image.open(image_stream)
                # Получение дескриптора
                if descriptor := await self._conn.calculate_descriptor(image):
                    context['descriptor'] = descriptor
                else:
                    text = 'Не удалось получить модель лица. Попробуйте другое фото.'
                    await bot.send_message(chat_id, text)
            case _:
                text = 'Сообщение должно содержать изображение!'
                await bot.send_message(chat_id, text)

    async def after_action_switcher(self, action: Action, context: ContextVars) -> SwitcherResult:
        if isinstance(action, Message) and action.text == 'Отмена':
            return 'UsersMenu' if 'user_id' not in context else 'UserPage'
        if 'descriptor' in context:
            return 'SaveUser' if 'user_id' not in context else 'UpdateUser'


class SaveUser(ClearVarsOnExit):
    """Сохранить пользователя."""
    def __init__(self, main_node_connection: MainNodeConnection):
        self._conn = main_node_connection

    async def on_enter(self, chat_id: int, bot: Bot, context: ContextVars) -> None:
        full_name, position, descriptor = context['full_name'], context['position'], context['descriptor']
        # TODO: Избавиться от full_name
        user_id = await self._conn.create_user(*full_name.split(), position)
        await self._conn.update_face_descriptor(user_id, descriptor)
        context['user_id'] = user_id
        await bot.send_message(chat_id, 'Пользователь сохранён.')

    async def after_enter_switcher(self, context: ContextVars) -> SwitcherResult:
        if 'user_id' in context:
            return 'UserPage'

    clearing_vars = ['full_name', 'position', 'descriptor']


class UpdateUser(ClearVarsOnExit):
    """Обновить пользователя."""
    def __init__(self, main_node_connection: MainNodeConnection):
        self._conn = main_node_connection

    async def on_enter(self, chat_id: int, bot: Bot, context: ContextVars) -> None:
        # TODO: Починить обновление пользователя
        # await self._conn.update_user(
        #     user_id=context['user_id'],
        #     *context.get('full_name'),
        #     position=context.get('position'),
        # )
        await bot.send_message(chat_id, 'Пользователь обновлён.')

    async def after_enter_switcher(self, context: ContextVars) -> SwitcherResult:
        if 'user_id' in context:
            return 'UserPage'

    clearing_vars = ['full_name', 'position', 'descriptor']


class UserPage(State):
    """Информация о пользователе."""
    def __init__(self, main_node_connection: MainNodeConnection):
        self._conn = main_node_connection

    options = [
        'Изменить ФИО',
        'Изменить должность',
        'Обновить модель лица',
        'Назад'
    ]
    text = md.text(
        md.hbold('Пользователь'),
        md.text(md.hitalic('ID:'), md.hcode('{id}')),
        md.text(md.hitalic('ФИО:'), md.hcode('{full_name}')),
        md.text(md.hitalic('Должность:'), md.hcode('{position}')),
        sep='\n',
    )

    async def on_enter(self, chat_id: int, bot: Bot, context: ContextVars) -> None:
        user_id = context['user_id']
        info = await self._conn.get_user_info(user_id)
        text = self.text.format(id=info.id, full_name=info.full_name, position=info.position)
        keyboard = make_simple_keyboard(*self.options)
        await bot.send_message(chat_id, text, reply_markup=keyboard, parse_mode='html'),

    async def message_handler(self, message: Message, chat_id: int, bot: Bot, _) -> None:
        if message.text not in self.options:
            await bot.send_message(chat_id, 'Недопустимый ввод!')

    async def after_action_switcher(self, action: Action, context: ContextVars) -> StateName | None:
        match action:
            case Message(text=text):
                match text:
                    case 'Изменить ФИО':
                        return 'WaitUserFullName'
                    case 'Изменить Должность':
                        return 'WaitUserPosition'
                    case 'Обновить модель лица':
                        return 'WaitUserFacePhoto'
                    case 'Назад':
                        remove_context_vars(context, 'user_id')
                        if 'user_search_query' in context:
                            return 'UsersSearchResults'
                        else:
                            return 'UsersMenu'


class WaitUserSearchQuery(StaticViewOnEnter):
    text = md.text(
        'Формат запроса:',
        md.hcode('{фамилия} {имя} {отчество}, {должность}'),
        md.text('Для пропуска параметра используйте «', md.hcode('?'), '».', sep=''),
        'Примеры:',
        md.hcode('Иванов Иван Иванович, ?'),
        md.hcode('Иванов ? ?, Студент'),
        md.hcode('Петров ? ?, Преподаватель'),
        md.hcode('? Александр Сергеевич, ?'),
        sep='\n',
    )
    keyboard = make_simple_keyboard('Отмена')

    @staticmethod
    def get_search_query(text: str) -> UserSearchQuery:
        query = {}
        match text.split(', '):
            case [full_name, position]:
                match full_name.split():
                    case [surname, name, patronymic] as parts:
                        for part in parts:
                            if part != '?' and not part.isalpha():
                                raise ValueError()
                        if surname != '?':
                            query['surname'] = surname
                        if name != '?':
                            query['name'] = name
                        if patronymic != '?':
                            query['patronymic'] = patronymic
                    case _:
                        raise ValueError()
                if position != '?':
                    query['position'] = position
            case _:
                raise ValueError()
        return query

    async def message_handler(self, message: Message, chat_id: int, bot: Bot, context: ContextVars) -> None:
        if message.text == 'Отмена':
            return
        try:
            query = self.get_search_query(message.text)
        except ValueError:
            await bot.send_message(chat_id, 'Неверный формат запроса!')
            return
        context['user_search_query'] = query

    async def after_action_switcher(self, action: Action, context: ContextVars) -> SwitcherResult:
        if action.text == 'Отмена':
            remove_context_vars(context, 'user_search_query')
            return 'AccessControlMenu' if 'room_id' in context else 'UsersMenu'
        if 'user_search_query' in context:
            return 'UsersSearchResults'


class UsersSearchResults(State):
    """Результаты поиска пользователей."""
    def __init__(self, main_node_connection: MainNodeConnection):
        self._conn = main_node_connection

    async def on_enter(self, chat_id: int, bot: Bot, context: ContextVars) -> None:
        query = context['user_search_query']
        users = await self._conn.search_users(query)
        keyboard = make_simple_keyboard('Назад')
        if len(users) > 0:
            inline_keyboard = make_simple_inline_keyboard({
                u.full_name: str(u.id) for u in users
            })
            keyboard = make_simple_keyboard('Назад')
            messages_ids = []
            m = await bot.send_message(chat_id, "Результаты поиска пользователей:", reply_markup=inline_keyboard)
            messages_ids.append(m.message_id)
            m = await bot.send_message(chat_id, "👆 нажмите для перехода", reply_markup=keyboard)
            messages_ids.append(m.message_id)
            context['messages'] = messages_ids
        else:
            await bot.send_message(chat_id, "Не найдено ни одного пользователя.", reply_markup=keyboard)

    async def callback_handler(self, query: CallbackQuery, chat_id: int, bot: Bot, context: ContextVars) -> None:
        context['user_id'] = int(query.data)

    async def message_handler(self, message: Message, chat_id: int, bot: Bot, _) -> None:
        if message.text != 'Назад':
            await bot.send_message(chat_id, 'Недопустимый ввод!')

    async def after_action_switcher(self, action: Action, context: ContextVars) -> SwitcherResult:
        match action:
            case Message(text='Назад'):
                remove_context_vars(context, 'user_id')
                return 'WaitUserSearchQuery'
            case _:
                if 'user_id' in context:
                    if 'room_id' in context:
                        remove_context_vars(context, 'user_search_query')
                        return 'SaveAccess'
                    else:
                        return 'UserPage'

    async def on_exit(self, chat_id: int, bot: Bot, context: ContextVars) -> None:
        for message_id in context.get('messages') or []:
            await bot.delete_message(chat_id, message_id)
        remove_context_vars(context, 'messages', )


class RoomsList(State):
    """Список контролируемых помещений."""
    def __init__(self, main_node_connection: MainNodeConnection):
        self._conn = main_node_connection

    async def on_enter(self, chat_id: int, bot: Bot, context: ContextVars) -> None:
        keyboard = make_simple_keyboard('Назад')
        controlling_rooms = await self._conn.get_controlling_rooms(chat_id)
        if len(controlling_rooms) == 0:
            await bot.send_message(chat_id, text='Вам недоступно управление помещениями.', reply_markup=keyboard)
            return

        inline_keyboard = make_simple_inline_keyboard({r.name: int(r.id) for r in controlling_rooms})
        message_ids = []
        message = await bot.send_message(chat_id, text='Вам доступно управление следующими помещениями:',
                                         reply_markup=inline_keyboard)
        message_ids.append(message.message_id)
        message = await bot.send_message(chat_id, text='👆 нажмите для выбора', reply_markup=keyboard)
        message_ids.append(message.message_id)
        context['messages'] = message_ids

    async def callback_handler(self, query: CallbackQuery, chat_id: int, bot: Bot, context: ContextVars) -> None:
        context['room_id'] = int(query.data)

    async def message_handler(self, message: Message, chat_id: int, bot: Bot, context: ContextVars) -> None:
        if message.text != 'Назад':
            await bot.send_message(chat_id, 'Недопустимый ввод!')

    async def after_action_switcher(self, action: Action, context: ContextVars) -> SwitcherResult:
        match action:
            case Message(text='Назад'):
                remove_context_vars(context, 'room_id')
                return 'MainMenu'
            case _:
                if 'room_id' in context:
                    return 'RoomPage'

    async def on_exit(self, chat_id: int, bot: Bot, context: ContextVars) -> None:
        for message_id in context['messages']:
            await bot.delete_message(chat_id, message_id)
        remove_context_vars(context, 'messages')


class RoomPage(RenderedViewOnEnter, SwitchStateByMessage):
    """Страница помещения."""
    def __init__(self, main_node_connection: MainNodeConnection):
        self._conn = main_node_connection

    options_switcher = {
        'Посещения': 'WaitVisitDate',
        'Задачи': 'TasksMenu',
        'Настройки доступа': 'AccessControlMenu',
        'Назад': 'RoomsList',
    }
    keyboard = make_simple_keyboard(*options_switcher.keys())
    text = md.text(
        md.hbold('Помещение'),
        md.text(md.hitalic('ID:'), md.hcode('{id}')),
        md.hitalic('Название:'),
        md.hcode('{name}'),
        md.hitalic('Последнее посещение:'),
        md.hcode('{datetime}'),
        sep='\n'
    )

    async def render_text(self, chat_id: int, context: ContextVars) -> str:
        room_id = context['room_id']
        room_info = await self._conn.get_room_info(room_id)
        last_visits = await self._conn.get_visits(room_id, Date.today())

        if len(last_visits) != 0:
            datetime = last_visits[-1].datetime.strftime('%H:%M %d.%m.%Y')
        else:
            datetime = '❌'
        return self.text.format(id=room_info.id, name=room_info.name, datetime=datetime)

    async def render_keyboard(self, chat_id: int, context: ContextVars) -> Keyboard:
        return self.keyboard


class WaitVisitDate(StaticViewOnEnter):
    """Ожидание ввода даты для просмотра посещений."""
    text = md.text(
        'Для просмотра посещений введите дату в следующем формате:',
        md.hcode('{день}.{месяц}.{год}'),
        md.text('Пример:', md.hcode('10.04.2022')),
        sep='\n'
    )
    keyboard = make_simple_keyboard(
        'Сегодня',
        'Вчера',
        'Назад'
    )

    @staticmethod
    def get_date(text: str) -> Date:
        match text.split('.'):
            case [day, month, year]:
                return Date(int(year), int(month), int(day))
            case _:
                raise ValueError()

    async def message_handler(self, message: Message, chat_id: int, bot: Bot, context: ContextVars) -> None:
        match message.text:
            case 'Назад':
                return
            case 'Сегодня':
                date = Date.today()
            case 'Вчера':
                date = Date.today() - timedelta(days=1)
            case text:
                try:
                    date = self.get_date(text)
                except ValueError:
                    await bot.send_message(chat_id, 'Недопустимый формат даты!')
                    return
        context['date'] = date.isoformat()

    async def after_action_switcher(self, action: Action, context: ContextVars) -> SwitcherResult:
        match action:
            case Message(text='Назад'):
                return 'RoomPage'
        if 'date' in context:
            return 'RoomVisits'


class RoomVisits(RenderedViewOnEnter):
    def __init__(self, main_node_connection: MainNodeConnection):
        self._conn = main_node_connection

    @staticmethod
    def format_visit(datetime_, full_name) -> str:
        return f"{datetime_.strftime('%H:%M')} – {md.hcode(full_name)}"

    async def render_text(self, chat_id: int, context: ContextVars) -> str:
        room_id, date = context['room_id'], Date.fromisoformat(context['date'])
        visits = await self._conn.get_visits(room_id, date)
        user_infos = await asyncio.gather(*(self._conn.get_user_info(v.user_id) for v in visits))
        text = f'В день {md.hbold(date.isoformat())} всего было посещений – {len(visits)}:\n'
        text += '\n'.join(self.format_visit(visit.datetime, user.full_name)
                          for visit, user in zip(visits, user_infos))
        return text

    async def render_keyboard(self, chat_id: int, context: ContextVars) -> Keyboard:
        return make_simple_keyboard('Назад')

    async def message_handler(self, message: Message, chat_id: int, bot: Bot, context: ContextVars) -> None:
        if message.text != 'Назад':
            await bot.send_message(chat_id, 'Недопустимый ввод!')

    async def after_action_switcher(self, action: Action, context: ContextVars) -> SwitcherResult:
        match action:
            case Message(text='Назад'):
                remove_context_vars(context, 'date')
                return 'WaitVisitDate'


class TasksMenu(StaticViewOnEnter, SwitchStateByMessage):
    """Меню «Задачи»."""
    text = 'Выберите задачу:'
    options_switcher = {
        'Открыть дверь сейчас': 'TaskOpenDoorNow',
        'Назад': 'RoomPage',
    }
    keyboard = make_simple_keyboard(*options_switcher.keys())


class TaskOpenDoorNow(State):
    """Открыть дверь сейчас."""
    def __init__(self, main_node_connection: MainNodeConnection):
        self._conn = main_node_connection

    async def on_enter(self, chat_id: int, bot: Bot, context: ContextVars) -> None:
        room_id = context['room_id']
        await self._conn.creat_open_door_task(chat_id, room_id)
        await bot.send_message(chat_id, 'Задача на открытие двери в помещение создана.')

    async def after_enter_switcher(self, _) -> SwitcherResult:
        return 'TasksMenu'


class AccessControlMenu(StaticViewOnEnter, SwitchStateByMessage):
    text = 'Выберете:'
    options_switcher = {
        'Разрешить доступ': 'WaitUserSearchQuery',
        'Запретить доступ': 'AccessedUsersList',
        'Назад': 'RoomPage'
    }
    keyboard = make_simple_keyboard(*options_switcher.keys())

    async def message_handler(self, message: Message, chat_id: int, bot: Bot, context: ContextVars) -> None:
        match message.text:
            case 'Разрешить доступ':
                context['accessed'] = True
            case 'Запретить доступ':
                context['accessed'] = False

class AccessedUsersList(State):
    """Список пользователей, имеющих доступ в помещение."""
    def __init__(self, main_node_connection: MainNodeConnection):
        self._conn = main_node_connection

    async def on_enter(self, chat_id: int, bot: Bot, context: ContextVars) -> None:
        users = await self._conn.get_accessed_users(context['room_id'])
        keyboard = make_simple_keyboard('Назад')
        if len(users) > 0:
            inline_keyboard = make_simple_inline_keyboard({
                u.full_name: str(u.id) for u in users
            })
            keyboard = make_simple_keyboard('Назад')
            messages_ids = []
            m = await bot.send_message(chat_id, f"Пользователи, имеющие доступ в помещение (всего {len(users)}):",
                                       reply_markup=inline_keyboard)
            messages_ids.append(m.message_id)
            m = await bot.send_message(chat_id, "👆 нажмите для запрета доступа", reply_markup=keyboard)
            messages_ids.append(m.message_id)
            context['messages'] = messages_ids
        else:
            await bot.send_message(
                chat_id, "Ни один пользователь не имеет доступа в это помещение.", reply_markup=keyboard)

    async def callback_handler(self, query: CallbackQuery, chat_id: int, bot: Bot, context: ContextVars) -> None:
        context['user_id'] = int(query.data)

    async def message_handler(self, message: Message, chat_id: int, bot: Bot, _) -> None:
        if message.text != 'Назад':
            await bot.send_message(chat_id, 'Недопустимый ввод!')

    async def after_action_switcher(self, action: Action, context: ContextVars) -> SwitcherResult:
        match action:
            case Message(text='Назад'):
                remove_context_vars(context, 'user_id', 'accessed', 'user_search_query')
                return 'AccessControlMenu'
            case _:
                if 'user_id' in context:
                    return 'SaveAccess'

    async def on_exit(self, chat_id: int, bot: Bot, context: ContextVars) -> None:
        for message_id in context.get('messages') or []:
            await bot.delete_message(chat_id, message_id)
        remove_context_vars(context, 'messages')


class SaveAccess(ClearVarsOnExit):
    def __init__(self, main_node_connection: MainNodeConnection):
        self._conn = main_node_connection

    async def on_enter(self, chat_id: int, bot: Bot, context: ContextVars) -> None:
        room_id, user_id, accessed = context['room_id'], context['user_id'], context['accessed']
        await self._conn.configure_access(room_id, user_id, accessed)
        user = await self._conn.get_user_info(user_id)
        room = await self._conn.get_room_info(room_id)
        access_word = 'разрешён' if accessed else 'запрещён'
        text = f"Пользователю «{user.full_name}» был {access_word} доступ в помещение «{room.name}»."
        await bot.send_message(chat_id, text)

    async def after_enter_switcher(self, context: ContextVars) -> SwitcherResult:
        return 'AccessControlMenu'

    clearing_vars = ['user_id', 'accessed', ]
