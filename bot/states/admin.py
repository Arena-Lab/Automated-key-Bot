"""FSM states for admin interactions"""

from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    """Admin interaction states"""

    # Product management
    adding_product_name = State()
    adding_product_description = State()
    adding_product_image = State()
    editing_product = State()

    # Key management
    adding_single_key = State()
    adding_bulk_keys = State()
    uploading_key_file = State()
    searching_keys = State()
    searching_orders = State()

    # Plan management
    adding_plan_name = State()
    adding_plan_duration = State()
    adding_plan_price = State()
    editing_plan = State()

    # Settings management
    editing_shop_name = State()
    editing_welcome_message = State()
    editing_upi_id = State()
    editing_qr_code = State()

    # Broadcast
    broadcast_message_type = State()
    broadcast_content = State()
    broadcast_file = State()

    # Reseller management
    adding_reseller = State()
    setting_reseller_discount = State()
