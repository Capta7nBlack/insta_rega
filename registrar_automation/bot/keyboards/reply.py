from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧪 Test Registration"), KeyboardButton(text="🚀 Real Registration")],
            [KeyboardButton(text="📋 My Registrations"), KeyboardButton(text="❌ Cancel Registration")]
        ],
        resize_keyboard=True,
        persistent=True
    )

def cancel_only():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Cancel Operation")]],
        resize_keyboard=True
    )
