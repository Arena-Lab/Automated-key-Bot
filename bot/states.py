"""FSM states for the key shop bot"""

from aiogram.fsm.state import State, StatesGroup


class CustomerStates(StatesGroup):
    waiting_for_utr = State()
    waiting_for_screenshot = State()


class AdminStates(StatesGroup):
    # Product creation wizard
    product_name = State()
    product_image = State()
    product_desc = State()
    product_plan_name = State()
    product_plan_price = State()
    product_plan_hours = State()

    # Guided key entry (product/plan chosen via buttons)
    adding_keys = State()

    # Product field edits: data = {pid, field}
    edit_field = State()
    edit_field_img = State()

    # Plan add/edit
    plan_add_name = State()
    plan_add_price = State()
    plan_add_hours = State()
    plan_edit_field = State()   # data = {plan_id, field}

    # Searches
    search_keys = State()
    search_orders = State()
    search_users = State()

    # Files / links / tutorial
    file_instructions = State()
    link_title = State()
    link_url = State()
    tutorial_video = State()

    # Broadcast
    broadcast_content = State()

    # Settings edits: data = {key}
    edit_setting = State()
