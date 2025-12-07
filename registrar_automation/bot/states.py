from aiogram.fsm.state import State, StatesGroup

class RegistrationFlow(StatesGroup):
    waiting_mode = State()          # User selects Test vs Real
    waiting_credentials = State()   # User inputs username:password
    waiting_schedule = State()      # User uploads schedule.txt
    selecting_date = State()        # User picks date from calendar
    selecting_time = State()        # User picks time
    confirming = State()            # Final review
