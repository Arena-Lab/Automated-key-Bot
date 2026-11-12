"""All keyboards - single consistent design system (bot/ui.py; renamed to avoid
collision with the legacy bot/keyboards/ package)"""

from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from typing import List, Dict, Any


def _ikb(rows: List[List[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


class KB:
    # ---------- Customer ----------

    @staticmethod
    def reply_menu() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🛍️ Purchase Keys"), KeyboardButton(text="🔑 My Keys")],
                [KeyboardButton(text="🎁 Setup Channel"), KeyboardButton(text="📞 Owner Contact")],
                [KeyboardButton(text="🔴 How to Buy?")],
                [KeyboardButton(text="🤝 Join Reseller")],
            ],
            resize_keyboard=True,
        )

    @staticmethod
    def products(products: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
        rows = []
        for p in products:
            stock = p.get("stock_total", 0)
            label = p["name"] if stock > 0 else f"{p['name']} (Out of Stock)"
            rows.append([InlineKeyboardButton(
                text=f"🎮 {label}",
                callback_data=f"prod_{p['_id']}" if stock > 0 else "noop",
            )])
        return _ikb(rows)

    @staticmethod
    def plans(plans: List[Dict[str, Any]], product_id: str) -> InlineKeyboardMarkup:
        rows, row = [], []
        for pl in plans:
            stock = pl.get("stock", 0)
            text = f"⏱️ {pl['name']} - ₹{pl['price']}" + ("" if stock > 0 else " 🔴")
            row.append(InlineKeyboardButton(
                text=text,
                callback_data=f"plan_{pl['_id']}" if stock > 0 else "noop",
            ))
            if len(row) == 2:
                rows.append(row); row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton(text="🔙 Products", callback_data="nav_products")])
        return _ikb(rows)

    @staticmethod
    def payment(order_id: str) -> InlineKeyboardMarkup:
        return _ikb([
            [InlineKeyboardButton(text="✅ Submit UTR", callback_data=f"pay_utr_{order_id}")],
            [InlineKeyboardButton(text="📸 Upload Screenshot", callback_data=f"pay_ss_{order_id}")],
            [InlineKeyboardButton(text="❌ Cancel Payment", callback_data=f"pay_cancel_{order_id}")],
        ])

    @staticmethod
    def order_actions(order_id: str) -> InlineKeyboardMarkup:
        return _ikb([
            [InlineKeyboardButton(text="🔑 View Key", callback_data=f"key_{order_id}")],
            [InlineKeyboardButton(text="📥 Files", callback_data=f"files_{order_id}")],
            [InlineKeyboardButton(text="🔙 Orders", callback_data="nav_orders")],
        ])

    @staticmethod
    def back_nav(target: str, label: str = "🔙 Back") -> InlineKeyboardMarkup:
        return _ikb([[InlineKeyboardButton(text=label, callback_data=target)]])

    # ---------- Admin ----------

    @staticmethod
    def admin_dashboard() -> InlineKeyboardMarkup:
        return _ikb([
            [InlineKeyboardButton(text="📊 Statistics", callback_data="adm_stats")],
            [InlineKeyboardButton(text="🛍️ Products", callback_data="adm_products")],
            [InlineKeyboardButton(text="🔑 Keys", callback_data="adm_keys")],
            [InlineKeyboardButton(text="💳 Payments", callback_data="adm_payments")],
            [InlineKeyboardButton(text="📦 Orders", callback_data="adm_orders")],
            [InlineKeyboardButton(text="👥 Customers", callback_data="adm_customers")],
            [InlineKeyboardButton(text="📁 Files & Links", callback_data="adm_files")],
            [InlineKeyboardButton(text="📢 Broadcast", callback_data="adm_broadcast")],
            [InlineKeyboardButton(text="⚙️ Settings", callback_data="adm_settings")],
            [InlineKeyboardButton(text="🛡️ Admins", callback_data="adm_admins")],
            [InlineKeyboardButton(text="🔄 Restart Bot", callback_data="adm_restart")],
            [InlineKeyboardButton(text="🚪 Exit", callback_data="adm_exit")],
        ])

    @staticmethod
    def admin_products(products: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
        rows = []
        for p in products:
            flag = "🟢" if p.get("status") == "active" else "🔴"
            rows.append([InlineKeyboardButton(
                text=f"{flag} {p['name']}",
                callback_data=f"adm_prod_{p['_id']}",
            )])
        rows.append([
            InlineKeyboardButton(text="➕ Add Product", callback_data="adm_prod_add"),
            InlineKeyboardButton(text="🔙 Dashboard", callback_data="adm_dash"),
        ])
        return _ikb(rows)

    @staticmethod
    def product_detail(pid: str) -> InlineKeyboardMarkup:
        return _ikb([
            [InlineKeyboardButton(text="📝 Edit Info", callback_data=f"adm_pe_{pid}")],
            [InlineKeyboardButton(text="⏱️ Plans", callback_data=f"adm_plans_{pid}"),
             InlineKeyboardButton(text="🔑 Keys", callback_data=f"adm_pkeys_{pid}")],
            [InlineKeyboardButton(text="📁 Files", callback_data=f"adm_pfiles_{pid}"),
             InlineKeyboardButton(text="🔗 Links", callback_data=f"adm_plinks_{pid}")],
            [InlineKeyboardButton(text="👁 View", callback_data=f"adm_pview_{pid}"),
             InlineKeyboardButton(text="🗑 Delete", callback_data=f"adm_pdel_{pid}")],
            [InlineKeyboardButton(text="🔙 Products", callback_data="adm_products")],
        ])

    @staticmethod
    def product_edit(pid: str) -> InlineKeyboardMarkup:
        return _ikb([
            [InlineKeyboardButton(text="✏️ Name", callback_data=f"adm_f_name_{pid}"),
             InlineKeyboardButton(text="📝 Description", callback_data=f"adm_f_desc_{pid}")],
            [InlineKeyboardButton(text="🖼 Image", callback_data=f"adm_f_img_{pid}"),
             InlineKeyboardButton(text="📊 Order", callback_data=f"adm_f_ord_{pid}")],
            [InlineKeyboardButton(text="🟢/🔴 Toggle", callback_data=f"adm_f_toggle_{pid}")],
            [InlineKeyboardButton(text="🔙 Product", callback_data=f"adm_prod_{pid}")],
        ])

    @staticmethod
    def plan_detail(plan_id: str, product_id: str) -> InlineKeyboardMarkup:
        return _ikb([
            [InlineKeyboardButton(text="✏️ Name", callback_data=f"adm_q_name_{plan_id}"),
             InlineKeyboardButton(text="💰 Price", callback_data=f"adm_q_price_{plan_id}"),
             InlineKeyboardButton(text="⏱ Hours", callback_data=f"adm_q_hours_{plan_id}")],
            [InlineKeyboardButton(text="🟢/🔴 Toggle", callback_data=f"adm_q_toggle_{plan_id}")],
            [InlineKeyboardButton(text="🗑 Delete", callback_data=f"adm_q_del_{plan_id}")],
            [InlineKeyboardButton(text="🔙 Plans", callback_data=f"adm_plans_{product_id}")],
        ])

    @staticmethod
    def verify_payment(order_id: str) -> InlineKeyboardMarkup:
        return _ikb([
            [InlineKeyboardButton(text="✅ Approve", callback_data=f"ver_ok_{order_id}"),
             InlineKeyboardButton(text="❌ Reject", callback_data=f"ver_no_{order_id}")],
            [InlineKeyboardButton(text="👤 Customer", callback_data=f"ver_cust_{order_id}")],
        ])

    @staticmethod
    def settings_menu() -> InlineKeyboardMarkup:
        return _ikb([
            [InlineKeyboardButton(text="🏪 Shop Name", callback_data="set_name"),
             InlineKeyboardButton(text="👋 Welcome Msg", callback_data="set_welcome")],
            [InlineKeyboardButton(text="📢 Channel", callback_data="set_channel"),
             InlineKeyboardButton(text="📞 Support", callback_data="set_support")],
            [InlineKeyboardButton(text="🏦 UPI ID", callback_data="set_upi"),
             InlineKeyboardButton(text="👤 Payee Name", callback_data="set_payee")],
            [InlineKeyboardButton(text="📋 Instructions", callback_data="set_instructions"),
             InlineKeyboardButton(text="🔧 Maintenance Msg", callback_data="set_maint")],
            [InlineKeyboardButton(text="🔴 How to Buy Text", callback_data="set_howto")],
            [InlineKeyboardButton(text="💳 Payment Mode", callback_data="adm_paymode"),
             InlineKeyboardButton(text="🔧 Maintenance ON/OFF", callback_data="adm_maintoggle")],
            [InlineKeyboardButton(text="🔙 Dashboard", callback_data="adm_dash")],
        ])

    @staticmethod
    def yes_no(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
        return _ikb([
            [InlineKeyboardButton(text="✅ Yes", callback_data=yes_cb),
             InlineKeyboardButton(text="❌ No", callback_data=no_cb)],
        ])
