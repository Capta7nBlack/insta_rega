from datetime import datetime, timedelta
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

def create_date_calendar():
    """
    Generates a rolling 14-day calendar.
    Adapted from t_marketingbot logic.
    """
    months_en = {
        1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr",
        5: "May", 6: "Jun", 7: "Jul", 8: "Aug",
        9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"
    }

    builder = InlineKeyboardBuilder()
    today = datetime.today()
    
    # Generate buttons for next 14 days
    for i in range(14):
        date = today + timedelta(days=i)
        # Button: "24 Oct"
        month_name = months_en[date.month]
        btn_text = f"{date.day} {month_name}"
        
        # Callback: "date_2023-10-24"
        builder.button(text=btn_text, callback_data=date.strftime("date_%Y-%m-%d"))

    builder.adjust(3) # 3 columns for better mobile view
    return builder.as_markup()


def create_time_picker():
    """
    Generates hour selection (09:00 - 17:00).
    """
    builder = InlineKeyboardBuilder()
    
    # Range is 9 to 17 inclusive (range end is exclusive, so use 18)
    for hour in range(9, 18):
        # Format: 09:00
        time_display = f"{hour:02d}:00"
        # Callback: time_09:00:00
        callback = f"time_{hour:02d}:00:00"
        
        builder.button(text=time_display, callback_data=callback)
        
    builder.adjust(3) # 3 columns looks good for 9 items
    return builder.as_markup()


def create_test_options_keyboard():
    """
    Special keyboard for Test Mode: Allows selecting a date OR running immediately.
    """
    builder = InlineKeyboardBuilder()
    
    # The big "Run Now" button for testing
    builder.button(text="⚡ Run Test Immediately", callback_data="test_immediate")
    
    # The normal calendar buttons (same logic as above)
    months_en = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
    today = datetime.today()
    
    for i in range(14):
        date = today + timedelta(days=i)
        month_name = months_en[date.month]
        btn_text = f"{date.day} {month_name}"
        builder.button(text=btn_text, callback_data=date.strftime("date_%Y-%m-%d"))

    builder.adjust(1, 3) # "Run Now" takes full row, then 3 cols for dates
    return builder.as_markup()



def create_confirmation_keyboard() -> InlineKeyboardMarkup:
    """
    Creates a keyboard for confirming or canceling the validated schedule.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Confirm & Continue", callback_data="confirm_schedule")
    builder.button(text="❌ Cancel", callback_data="cancel_flow")
    builder.adjust(1)
    return builder.as_markup()
