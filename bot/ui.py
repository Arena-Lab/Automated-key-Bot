"""All keyboards - single consistent design system (bot/ui.py; renamed to avoid
collision with the legacy bot/keyboards/ package)"""

from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from typing import List, Dict, Any


def _ikb(rows: List[List[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def platform_icon(platform: str) -> str:
    return {
        "Android": "🤖", "iOS": "🍎", "Both": "💻",
        "iPad": "📱", "iPhone": "📱",
    }.get(platform or "", "🎮")


class KB:
    # ---------- Customer ----------

    @staticmethod
    def reply_menu() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🛍️ Purchase Keys"), KeyboardButton(text="🔑 My Keys")],
                [KeyboardButton(text="🎁 Setup Channel"), KeyboardButton(text="📞 Owner Contact")],
                [KeyboardButton(text="🔴 How to Buy?")],
                [KeyboardButton(text="👑 Resellers")],
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
                callback_data=f"prod_{p['_id']}",
            )])
        return _ikb(rows)

    @staticmethod
    def plans(plans: List[Dict[str, Any]], product_id: str) -> InlineKeyboardMarkup:
        rows, row = [], []
        for pl in plans:
            try:
                price = f"{float(pl['price']):g}"
            except (TypeError, ValueError):
                price = str(pl["price"])
            row.append(InlineKeyboardButton(
                text=f"⏱️ {pl['name']} - ₹{price}",
                callback_data=f"plan_{pl['_id']}",
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
            [InlineKeyboardButton(text="📊 Stats", callback_data="adm_stats"),
             InlineKeyboardButton(text="🛍️ Products", callback_data="adm_products")],
            [InlineKeyboardButton(text="📦 Orders", callback_data="adm_orders"),
             InlineKeyboardButton(text="👥 Customers", callback_data="adm_customers")],
            [InlineKeyboardButton(text="📁 Files", callback_data="adm_files"),
             InlineKeyboardButton(text="🔑 Key Backup", callback_data="adm_keybackup")],
            [InlineKeyboardButton(text="🗄 Database Backup", callback_data="adm_dbbak")],
            [InlineKeyboardButton(text="📢 Broadcast", callback_data="adm_broadcast"),
             InlineKeyboardButton(text="🎯 Promo", callback_data="adm_promo")],
            [InlineKeyboardButton(text="🔄 Restart", callback_data="adm_restart"),
             InlineKeyboardButton(text="🚪 Exit", callback_data="adm_exit")],
        ])

    @staticmethod
    def admin_products(products: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
        rows = []
        for p in products:
            flag = "🟢" if p.get("status") == "active" else "🔴"
            rows.append([InlineKeyboardButton(
                text=f"{flag} {platform_icon(p.get('platform'))} {p['name']}",
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
            [InlineKeyboardButton(text="⏱️ Plans", callback_data=f"adm_plans_{pid}"),
             InlineKeyboardButton(text="🔑 Keys", callback_data=f"adm_pkeys_{pid}")],
            [InlineKeyboardButton(text="📁 Files & Links", callback_data=f"adm_pfiles_{pid}")],
            [InlineKeyboardButton(text="👁 Preview", callback_data=f"adm_pview_{pid}"),
             InlineKeyboardButton(text="📝 Edit", callback_data=f"adm_pe_{pid}")],
            [InlineKeyboardButton(text="🟢/🔴 Toggle", callback_data=f"adm_f_toggle_{pid}"),
             InlineKeyboardButton(text="🗑 Delete", callback_data=f"adm_pdel_{pid}")],
            [InlineKeyboardButton(text="🔙 Products", callback_data="adm_products")],
        ])

    @staticmethod
    def product_edit(pid: str) -> InlineKeyboardMarkup:
        return _ikb([
            [InlineKeyboardButton(text="✏️ Name", callback_data=f"adm_f_name_{pid}"),
             InlineKeyboardButton(text="📝 Description", callback_data=f"adm_f_desc_{pid}")],
            [InlineKeyboardButton(text="📊 Display Order", callback_data=f"adm_f_ord_{pid}"),
             InlineKeyboardButton(text="📱 Platform", callback_data=f"adm_f_plat_{pid}")],
            [InlineKeyboardButton(text="🟢/🔴 Show-Hide", callback_data=f"adm_f_toggle_{pid}")],
            [InlineKeyboardButton(text="🔙 Product", callback_data=f"adm_prod_{pid}")],
        ])

    @staticmethod
    def keys_view(plan_id: str, keys: list) -> InlineKeyboardMarkup:
        rows = []
        for k in keys[:30]:
            icon = "🟢" if k.get("status") == "available" else "⚫"
            label = str(k.get("key_value", ""))[:30]
            rows.append([InlineKeyboardButton(
                text=f"{icon} {label}", callback_data=f"adm_kd_{k['_id']}")])
        rows.append([InlineKeyboardButton(text="➕ Add Keys", callback_data=f"adm_kadd_{plan_id}")])
        rows.append([InlineKeyboardButton(text="🔙 Product Keys", callback_data="adm_keys_menu")])
        return _ikb(rows)

    @staticmethod
    def confirm_delete(text: str, yes_cb: str, no_cb: str = "adm_prod_{pid}") -> InlineKeyboardMarkup:
        return _ikb([
            [InlineKeyboardButton(text="✅ Yes, Delete", callback_data=yes_cb),
             InlineKeyboardButton(text="❌ Cancel", callback_data=no_cb)],
        ])

    @staticmethod
    def plan_detail(plan_id: str, product_id: str) -> InlineKeyboardMarkup:
        return _ikb([
            [InlineKeyboardButton(text="✏️ Name", callback_data=f"adm_q_name_{plan_id}"),
             InlineKeyboardButton(text="💰 Price", callback_data=f"adm_q_price_{plan_id}")],
            [InlineKeyboardButton(text="🟢/🔴 Toggle", callback_data=f"adm_q_toggle_{plan_id}")],
            [InlineKeyboardButton(text="🗑 Delete", callback_data=f"adm_q_del_{plan_id}")],
            [InlineKeyboardButton(text="🔙 Plans", callback_data=f"adm_plans_{product_id}")],
        ])

    @staticmethod
    def settings_menu(maint_on: bool = False,
                      db_backup_on: bool = True) -> InlineKeyboardMarkup:
        maint_label = "🔴 Maintenance: ON" if maint_on else "🟢 Maintenance: OFF"
        db_label = "🗄 DB Backup: ON" if db_backup_on else "🗄 DB Backup: OFF"
        return _ikb([
            [InlineKeyboardButton(text="🏪 Shop Name", callback_data="set_name"),
             InlineKeyboardButton(text="👋 Welcome Msg", callback_data="set_welcome")],
            [InlineKeyboardButton(text="📢 Official Channel", callback_data="set_channel"),
             InlineKeyboardButton(text="🎁 Setup Channel", callback_data="set_setup")],
            [InlineKeyboardButton(text="📞 Support", callback_data="set_support"),
             InlineKeyboardButton(text="🔧 Maintenance Msg", callback_data="set_maint")],
            [InlineKeyboardButton(text="🔴 How to Buy Text", callback_data="set_howto")],
            [InlineKeyboardButton(text=db_label, callback_data="adm_dbbak_toggle")],
            [InlineKeyboardButton(text=maint_label, callback_data="adm_maintoggle")],
            [InlineKeyboardButton(text="🔙 Dashboard", callback_data="adm_dash")],
        ])

    @staticmethod
    def yes_no(yes_cb: str, no_cb: str) -> InlineKeyboardMarkup:
        return _ikb([
            [InlineKeyboardButton(text="✅ Yes", callback_data=yes_cb),
             InlineKeyboardButton(text="❌ No", callback_data=no_cb)],
        ])
