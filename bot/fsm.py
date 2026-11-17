"""FSM states (renamed to avoid collision with legacy bot/states/ package)"""

from aiogram.fsm.state import State, StatesGroup


class CustomerStates(StatesGroup):
    waiting_for_utr = State()
    waiting_for_screenshot = State()


class AdminStates(StatesGroup):
    product_name = State()
    product_platform = State()
    product_plans_pick = State()
    product_plans_prices = State()
    product_plans_custom = State()
    adding_keys = State()
    edit_field = State()
    edit_field_img = State()
    plan_add_name = State()
    plan_add_price = State()
    plan_add_hours = State()
    plan_edit_field = State()
    search_keys = State()
    search_orders = State()
    search_users = State()
    file_instructions = State()
    link_title = State()
    link_url = State()
    tutorial_video = State()
    broadcast_content = State()
    broadcast_link = State()
    promo_text = State()
    revenue_edit = State()
    edit_setting = State()
    # reseller admin
    rs_amount = State()
    rs_search = State()
    rs_code_amount = State()
    rs_code_expiry = State()
    rs_code_bulk = State()
    rs_price_plan = State()
    rs_price_value = State()
    rs_override_reseller = State()
    rs_override_plan = State()
    rs_override_value = State()
    rs_suspend_reason = State()
    rs_min_recharge = State()


class ResellerStates(StatesGroup):
    redeem_code = State()
    buy_confirm = State()
