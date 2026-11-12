"""Premium emoji helper - uses Telegram custom emoji when emoji-id is configured,
falls back to the unicode emoji otherwise. Works in message text/captions only
(button labels cannot render custom emoji)."""

# Map friendly keys -> (unicode_fallback, premium_emoji_id or None)
# Fill emoji_id values from your premium emoji pack (forward a message with the
# emoji to @RawDataBot or use the sticker's emoji_id).
PREMIUM_EMOJIS = {
    "shop": ("🛍️", None),
    "key": ("🔑", None),
    "box": ("📦", None),
    "money": ("💰", None),
    "channel": ("📢", None),
    "gift": ("🎁", None),
    "support": ("💬", None),
    "book": ("📖", None),
    "check": ("✅", None),
    "cross": ("❌", None),
    "warn": ("⚠️", None),
    "clock": ("⏳", None),
    "trophy": ("⚜️", None),
}


def pe(key: str) -> str:
    """Return premium emoji HTML if id configured, else unicode fallback"""
    fallback, emoji_id = PREMIUM_EMOJIS.get(key, ("✨", None))
    if emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
    return fallback
