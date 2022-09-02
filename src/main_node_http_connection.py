import logging
from datetime import date as Date, datetime, timedelta
from io import BytesIO
from typing import Any

from PIL import Image

from bot.states import MainNodeConnection, VisitInfo, RoomInfo, UserSearchQuery, UserInfo, Descriptor

logger = logging.getLogger('MAIN_NODE_HTTP_CONNECTION')

def _except_requests_exceptions(func):
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            return result
        except requests.ConnectionError:
            raise Exception('Подключение не установлено')
    return wrapper

class MainNodeHTTPConnection(MainNodeConnection):
    def __init__(self, main_node_host: str, admin_token: str):
        self._host_url = f"http://{main_node_host}/"
        self._session = requests.Session()
        self._session.headers['Admin-Token'] = admin_token

    async def calculate_descriptor(self, image: Image.Image) -> Descriptor | None:
        data = self._post('access/calculate_descriptor',
                          files={'image': _image_as_file(image)})
        return data['result']['features'] if data['success'] else None

    async def create_user(self, surname: str, name: str, patronymic: str, position: str) -> int:
        user_fields = {
            'surname': surname,
            'name': name,
            'patronymic': patronymic,
            'position': position
        }
        data = self._post('user', data=user_fields)
        return data['result']['id'] if data['success'] else print("Can't create user.")

    async def update_user(self, user_id: int, surname: str, name: str, patronymic: str, position: str) -> None:
        pass

    async def update_face_descriptor(self, user_id: int, descriptor: list[float]):
        descriptor_updating = {
            'user_id': user_id,
            'descriptor': {
                'features': descriptor
            }
        }
        data = self._post('access/update_descriptor',
                          data=descriptor_updating)
        if not data['success']:
            print('Cant update descriptor.')

    async def get_user_info(self, user_id: int) -> UserInfo | None:
        data = self._get('user', {'user_id': user_id})
        return UserInfo(**data['result']) if data['success'] else None

    async def search_users(self, query: UserSearchQuery, limit: int = None, offset: int = None) -> list[UserInfo]:
        data = self._get('users')
        users = [UserInfo(**u) for u in data['result']['users']]
        results = []
        surname, name, patronymic, position = \
            query.get('surname'), query.get('name'), query.get('patronymic'), query.get('position')
        for user in users:
            surname_is_equal = user.surname == surname or surname is None
            name_is_equal = user.name == name or name is None
            patronymic_is_equal = user.patronymic == patronymic or patronymic is None
            position_is_equal = user.position == position or position is None

            if all([surname_is_equal, name_is_equal, patronymic_is_equal, position_is_equal]):
                results.append(user)
        return results

    async def get_available_user_positions(self) -> list[str]:
        return ["Студент", "Преподаватель", "Сотрудник"]

    async def get_controlling_rooms(self, manager_id: int) -> list[RoomInfo]:
        data = self._get('rooms', data={'manager_id': manager_id})
        return [RoomInfo(**r) for r in data['result']['rooms']]

    async def get_room_info(self, room_id: int) -> RoomInfo:
        data = self._get('room', data={'room_id': room_id})
        return RoomInfo(**data['result'])

    async def get_visits(self, room_id: int, date: Date) -> list[VisitInfo]:
        data = self._get('access/visits', data={'date': date.isoformat(), 'room_id': room_id})
        visit_infos = []
        for visit in data['result']['visits']:
            datetime_ = datetime.fromisoformat(visit['datetime']) + timedelta(hours=7)
            info = VisitInfo(datetime_, visit['user_id'])
            visit_infos.append(info)
        return visit_infos

    async def creat_open_door_task(self, manager_id: int, room_id: int) -> None:
        task_creation = {
            'room_id': room_id,
            'type': 'OPEN_DOOR',
            'kwargs': {}
        }
        self._post('task', data=task_creation)

    async def configure_access(self, room_id: int, user_id: int, accessed: bool) -> None:
        access_configuration = {
            'room_id': room_id,
            'user_id': user_id,
            'accessed': accessed
        }
        self._post('access/configure', data=access_configuration)

    async def get_accessed_users(self, room_id: int) -> list[UserInfo]:
        data = self._get('access/users', data={'room_id': room_id})
        return [UserInfo(**u) for u in data['result']['users']]

    @_except_requests_exceptions
    def _post(self, url: str, data: dict[str, Any] = None,
              files: dict[str, BytesIO] = None, headers: dict[str, str] = None) -> dict[str, Any]:
        url = self._host_url + url
        response = self._session.post(url, json=data, files=files, headers=headers)
        return response.json()

    @_except_requests_exceptions
    def _get(self, url: str, data: dict[str, str] = None) -> dict[str, Any]:
        url = self._host_url + url
        response = self._session.get(url, json=data)
        return response.json()


def _image_as_file(image: Image.Image) -> BytesIO:
    virtual_file = BytesIO()
    image.save(virtual_file, 'JPEG')
    virtual_file.seek(0)
    return virtual_file
