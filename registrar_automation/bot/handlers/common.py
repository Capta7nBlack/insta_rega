from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from bot.keyboards.reply import main_menu

router = Router()

@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🎓 **Registrar Automation Bot**\n"
        "Select a mode to begin.",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

@router.message(F.text == "❌ Cancel Operation")
@router.message(Command("cancel"))
async def cmd_cancel_flow(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Operation cancelled.", reply_markup=main_menu())
