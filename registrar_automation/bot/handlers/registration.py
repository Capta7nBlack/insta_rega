import asyncio
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile
from aiogram.filters import Command

from bot.states import RegistrationFlow
from bot.keyboards.reply import cancel_only, main_menu
from bot.keyboards.builders import create_date_calendar, create_time_picker, create_test_options_keyboard
from bot.services.api_client import BackendAPI

router = Router()

# --- Step 1: Mode Selection ---
@router.message(F.text.in_({"🧪 Test Registration", "🚀 Real Registration"}))
async def start_reg(message: types.Message, state: FSMContext):
    await state.clear()
    mode = "real" if "Real" in message.text else "test"
    await state.update_data(mode=mode)
    
    await message.answer(
        f"Selected Mode: **{mode.upper()}**\n\n"
        "Please enter your university credentials in this format:\n"
        "`username:password`",
        reply_markup=cancel_only(),
        parse_mode="Markdown"
    )
    await state.set_state(RegistrationFlow.waiting_credentials)

# --- Step 2: Credential Validation (CRITICAL STEP) ---
@router.message(RegistrationFlow.waiting_credentials)
async def validate_credentials(message: types.Message, state: FSMContext):
    text = message.text.strip()
    
    if ":" not in text:
        await message.answer("❌ Invalid format. Please use `username:password`")
        return

    username, password = text.split(":", 1)
    username = username.strip()
    password = password.strip()
    
    data = await state.get_data()
    mode = data.get("mode", "test")
    
    msg = await message.answer("🔐 Validating credentials with university...")
    
    # Call Backend Service
    is_valid, error_msg = await BackendAPI.validate_user(username, password, mode)
    
    if not is_valid:
        await msg.edit_text(f"❌ **Validation Failed**\nReason: {error_msg}\n\nPlease try again.", parse_mode="Markdown")
        return # Stay in same state
        
    # If valid, save and proceed
    await state.update_data(username=username, password=password)
    await msg.edit_text("✅ **Credentials Verified.**")
    
    await message.answer(
        "Now, please upload your **schedule.txt** file.",
        reply_markup=cancel_only()
    )
    await state.set_state(RegistrationFlow.waiting_schedule)

# --- Step 3: Schedule Upload & Processing ---
@router.message(RegistrationFlow.waiting_schedule, F.document)
async def process_schedule(message: types.Message, state: FSMContext):
    file = await message.bot.get_file(message.document.file_id)
    content = await message.bot.download_file(file.file_path)
    schedule_text = content.read().decode('utf-8')
    
    data = await state.get_data()
    
    msg = await message.answer("⏳ **Analyzing Schedule...**\nThis uses the Test Server to safely validate your schedule file.")
    
    # Start Scraper Task
    task_id = await BackendAPI.validate_schedule(
        data['username'], 
        data['password'], 
        schedule_text
    )
    
    if not task_id:
        await msg.edit_text("❌ Failed to start validation task.")
        return

    # Poll for results
    for _ in range(30): # Timeout after 60 seconds
        await asyncio.sleep(2)
        status = await BackendAPI.get_schedule_status(task_id)
        
        if status['status'] == 'success':
            await state.update_data(validated_courses=status['result'])
            await msg.edit_text("✅ **Schedule Verified!** Course IDs scraped.")
            
            if data.get('mode') == 'test':
                keyboard = create_test_options_keyboard()
                text = "📅 **Select Test Date** or **Run Immediately**:"
            else:
                keyboard = create_date_calendar()
                text = "📅 **Select Registration Date:**"

            # Show Date Picker
            await message.answer(
                "📅 **Select Registration Date:**", 
                reply_markup=keyboard,
                parse_mode="Markdown"
            )


            await state.set_state(RegistrationFlow.selecting_date)
            return
            
        elif status['status'] == 'failed':
            await msg.edit_text(f"❌ Error: {status.get('error')}")
            return
            
    await msg.edit_text("❌ Validation timed out. Please try again!")


@router.callback_query(F.data == "test_immediate", RegistrationFlow.selecting_date)
async def run_test_immediate(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    # Prepare payload with special time string
    payload = {
        "chat_id": callback.message.chat.id,
        "username": data['username'],
        "password": data['password'],
        "target_time_str": "NOW", # This triggers immediate logic in backend
        "mode": "test", # Force test mode for safety
        "validated_courses": data['validated_courses']
    }
    
    await callback.message.edit_text("🚀 **Initializing Immediate Test Run...**")
    
    try:
        res = await BackendAPI.create_job(payload)
        
        await callback.message.bot.send_message(
            chat_id=callback.message.chat.id,
            text=(
                f"✅ **Test Job Started!**\n\n"
                f"🆔 Job ID: `{res['job_id']}`\n"
                f"🎯 Mode: **TEST**\n"
                f"🕒 Trigger Time: `{res['target_time']}` (Approx +60s)\n\n"
                "I will verify login in ~48 seconds."
            ),
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )
        await state.clear()
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Failed to schedule: {str(e)}")
    
    await callback.answer()



# --- Step 4: Date Selection ---
@router.callback_query(F.data.startswith("date_"), RegistrationFlow.selecting_date)
async def date_selected(callback: types.CallbackQuery, state: FSMContext):
    selected_date = callback.data.split("_")[1]
    await state.update_data(target_date=selected_date)
    
    await callback.message.edit_text(
        f"📅 Date: **{selected_date}**\n\n⏰ **Select Start Time:**",
        reply_markup=create_time_picker(),
        parse_mode="Markdown"
    )
    await state.set_state(RegistrationFlow.selecting_time)
    await callback.answer()

# --- Step 5: Time Selection & Final Submit ---
@router.callback_query(F.data.startswith("time_"), RegistrationFlow.selecting_time)
async def time_selected(callback: types.CallbackQuery, state: FSMContext):
    selected_time = callback.data.split("_")[1] # 09:00:00
    data = await state.get_data()
    
    # Construct final datetime
    final_dt = f"{data['target_date']} {selected_time}"
    
    payload = {
        "chat_id": callback.message.chat.id,
        "username": data['username'],
        "password": data['password'],
        "target_time_str": final_dt,
        "mode": data['mode'],
        "validated_courses": data['validated_courses']
    }
    
    await callback.message.edit_text("🚀 Scheduling Registration...")
    
    try:
        res = await BackendAPI.create_job(payload)
        
        await callback.message.bot.send_message(
            chat_id=callback.message.chat.id,
            text=(
                f"✅ **Job Created Successfully!**\n\n"
                f"🆔 Job ID: `{res['job_id']}`\n"
                f"🎯 Mode: **{res['mode'].upper()}**\n"
                f"🕒 Trigger Time: `{res['target_time']}`\n\n"
                "I will verify login 20 seconds before this time."
            ),
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )
        await state.clear()
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Failed to schedule: {str(e)}")
        
    await callback.answer()

# --- Step 6: Job Management Handlers ---
@router.message(F.text == "📋 My Registrations")
async def list_jobs(message: types.Message):
    jobs = await BackendAPI.get_active_jobs(message.chat.id)
    if not jobs:
        await message.answer("You have no active registration jobs.")
        return
        
    text = "📋 **Your Active Registrations:**\n\n"
    for job in jobs:
        text += (
            f"🆔 `{job['job_id']}`\n"
            f"🕒 {job['target_time']} ({job['mode']})\n"
            f"📚 Courses: {', '.join(job['courses'])}\n"
            "-------------------\n"
        )
    await message.answer(text, parse_mode="Markdown")

@router.message(F.text == "❌ Cancel Registration")
async def cancel_job_prompt(message: types.Message):
    await message.answer("To cancel a registration, send command:\n`/cancel_registration <job_id>`", parse_mode="Markdown")

@router.message(Command("cancel_registration"))
async def cancel_registration_action(message: types.Message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
             await message.answer("Usage: `/cancel_registration <job_id>`", parse_mode="Markdown")
             return
             
        job_id = parts[1]
        success = await BackendAPI.cancel_job(message.chat.id, job_id)
        if success:
            await message.answer(f"✅ Registration `{job_id}` cancelled.", parse_mode="Markdown")
        else:
            await message.answer("❌ Job not found or failed to cancel.")
    except Exception:
        await message.answer("Usage: `/cancel_registration <job_id>`", parse_mode="Markdown")
