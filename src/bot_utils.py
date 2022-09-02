from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton


def make_simple_keyboard(*button_texts: str, row_width: int = 1) -> ReplyKeyboardMarkup:
    keyboard = ReplyKeyboardMarkup(row_width=row_width, one_time_keyboard=True, resize_keyboard=True)
    for text in button_texts:
        button = KeyboardButton(text)
        keyboard.insert(button)
    return keyboard


def make_simple_inline_keyboard(buttons_callbacks: dict[str, str], row_width: int = 1) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardMarkup(row_width=row_width)
    for text, data in buttons_callbacks.items():
        button = InlineKeyboardButton(text, callback_data=data)
        keyboard.insert(button)
    return keyboard

