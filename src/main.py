from aiogram import Bot, Dispatcher, executor
from aiogram.types import ContentTypes

from main_node_http_connection import MainNodeHTTPConnection
from state_machine import StateMachine
from state_machine.storages import SQLiteStateMachineStorage
from bot.states import (
    MainMenu, UsersMenu, WaitUserFullName, WaitUserPosition,
    WaitUserFacePhoto, SaveUser, UpdateUser, UserPage,
    WaitUserSearchQuery, UsersSearchResults, RoomsList, RoomPage,
    WaitVisitDate, RoomVisits, TasksMenu, TaskOpenDoorNow, AccessControlMenu, SaveAccess, AccessedUsersList,
)


def main():
    bot = Bot(token='5313341593:AAFcOF_kyOBKfKEOwIRBjpiMsOEOhE8mokU')
    dispatcher = Dispatcher(bot)

    storage = SQLiteStateMachineStorage(db_path=r'C:\Users\Victor\Desktop\AccessControlSystem\room_manager_interface\db.sqlite')
    main_node = MainNodeHTTPConnection('localhost:8080', '126b1e14d1f0a1966a8859a9412e436e')
    state_machine = StateMachine(
        states=[
            menu := MainMenu(),
            UsersMenu(),
            WaitUserFullName(),
            WaitUserPosition(main_node),
            WaitUserFacePhoto(main_node),
            SaveUser(main_node),
            UpdateUser(main_node),
            UserPage(main_node),
            WaitUserSearchQuery(),
            UsersSearchResults(main_node),
            RoomsList(main_node),
            RoomPage(main_node),
            WaitVisitDate(),
            RoomVisits(main_node),
            TasksMenu(),
            TaskOpenDoorNow(main_node),
            AccessControlMenu(),
            SaveAccess(main_node),
            AccessedUsersList(main_node),
        ],
        default_state=menu,
        state_machine_storage=storage,
        bot=bot,
    )

    content_types = ContentTypes.TEXT | ContentTypes.DOCUMENT | ContentTypes.PHOTO
    dispatcher.register_message_handler(state_machine.handle_action, content_types=content_types)
    dispatcher.register_callback_query_handler(state_machine.handle_action)

    executor.start_polling(dispatcher, skip_updates=True)


if __name__ == '__main__':
    main()
