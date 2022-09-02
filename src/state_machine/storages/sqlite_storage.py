import json
import sqlite3

from ..state_machine import StateMachineStorage, StateName, ContextVars

sqlite3.register_adapter(dict, json.dumps)
sqlite3.register_converter('json', json.loads)


class SQLiteStateMachineStorage(StateMachineStorage):
    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        self._conn.row_factory = sqlite3.Row
        self._create_state_table()  # if not exist
        self._create_context_table()

    async def get_state(self, chat_id: int) -> StateName | None:
        return self._get_state(chat_id)

    async def set_state(self, chat_id: int, state_name: str) -> None:
        return self._set_state(chat_id, state_name)

    async def get_context(self, chat_id: int) -> ContextVars | None:
        return self._get_context(chat_id)

    async def set_context(self, chat_id: int, context: ContextVars) -> None:
        return self._set_context(chat_id, context)

    def _get_state(self, chat_id: int) -> str | None:
        query = 'select state_name from "State" where chat_id=:chat_id'
        record = self._conn.execute(query, {'chat_id': chat_id}).fetchone()
        return record['state_name'] if record is not None else None

    def _set_state(self, chat_id: int, state_name: str) -> None:
        query = '''
            insert into "State" (chat_id, state_name) values (:chat_id, :state_name)
            on conflict (chat_id) do update set state_name=:state_name;
        '''
        self._conn.execute(query, {'chat_id': chat_id, 'state_name': state_name})
        self._conn.commit()

    def _get_context(self, chat_id: int) -> ContextVars | None:
        query = 'select context from "Context" where chat_id=:chat_id'
        record = self._conn.execute(query, {'chat_id': chat_id}).fetchone()
        return record['context'] if record is not None else None

    def _set_context(self, chat_id: int, context: ContextVars) -> None:
        query = '''
            insert into "Context"(chat_id, context) values (:chat_id, :context)
            on conflict(chat_id) do update set context=:context;
        '''
        self._conn.execute(query, {'chat_id': chat_id, 'context': context})
        self._conn.commit()
        
    def _create_context_table(self) -> None:
        query = '''
            create table Context (
                chat_id INTEGER PRIMARY KEY,
                context json    NOT NULL
            );
        '''
        try:
            self._conn.execute(query)
            self._conn.commit()
        except sqlite3.OperationalError:
            pass

    def _create_state_table(self) -> None:
        query = '''
            create table State (
                chat_id    INTEGER PRIMARY KEY,
                state_name TEXT    NOT NULL
            );
        '''
        try:
            self._conn.execute(query)
            self._conn.commit()
        except sqlite3.OperationalError:
            pass
