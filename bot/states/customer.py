"""FSM states for customer interactions"""

from aiogram.fsm.state import State, StatesGroup


class CustomerStates(StatesGroup):
    """Customer interaction states"""

    waiting_for_payment_utr = State()
    waiting_for_payment_screenshot = State()
