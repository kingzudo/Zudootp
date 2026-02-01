import asyncio
import json
import os
import re
from datetime import datetime
from io import BytesIO

from pyrogram import Client
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
import logging
import qrcode

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ===================== CONFIG =====================
BOT_TOKEN = "8309358322:AAFTTIQhHAIEy_7B42mspLUgBNClKFM1-ck"
OWNER_ID = 7661825494
API_ID = 33628258
API_HASH = "0850762925b9c1715b9b122f7b753128"

# Force Join Settings
SUPPORT_CHANNEL_ID = -1003782083448
SUPPORT_GROUP_ID = -1003857205137
SUPPORT_CHANNEL_LINK = "https://t.me/zudootp"
SUPPORT_GROUP_LINK = "https://t.me/zudootpsupport"

# UPI Details
UPI_ID = "fearlessaditya@fam"
UPI_NAME = "Aditya"

# Database file
DB_FILE = "virtual_bot_data.json"

# Membership cache (1 hour)
membership_cache = {}
CACHE_DURATION = 3600

# ===================== STATES =====================
(
    WAITING_FOR_AMOUNT,
    WAITING_FOR_COUPON,
    WAITING_FOR_SCREENSHOT,
    WAITING_FOR_COUNTRY,
    WAITING_FOR_PRICE,
    WAITING_FOR_SESSION,
    WAITING_FOR_DISCOUNT_AMOUNT,
    WAITING_FOR_COUPON_AMOUNT,
    WAITING_FOR_2FA,
    WAITING_FOR_LOGIN_STATUS,
    WAITING_FOR_DISCOUNT_CODE,
    WAITING_FOR_BOT_PHOTO,
    WAITING_FOR_QUANTITY,
    WAITING_FOR_ADD_MORE_SESSIONS,
    WAITING_FOR_BROADCAST_MESSAGE,
    WAITING_FOR_TARGET_USER_ID,
    WAITING_FOR_TARGET_AMOUNT
) = range(17)

# ===================== DB LOAD/SAVE =====================
def load_data():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, 'r') as f:
            return json.load(f)
    return {
        "users": {},
        "accounts": {},
        "discount_codes": {},
        "coupons": {},
        "pending_payments": {},
        "bot_photo": None,
        "states": {},
        "used_coupons": {},
        "used_discounts": {}
    }

def ensure_keys(d):
    for key in ["users", "accounts", "discount_codes", "coupons", "pending_payments", "states", "used_coupons", "used_discounts"]:
        if key not in d:
            d[key] = {}
    if "bot_photo" not in d:
        d["bot_photo"] = None
    return d

def save_data(d):
    with open(DB_FILE, 'w') as f:
        json.dump(d, f, indent=2)

data = ensure_keys(load_data())

# ===================== HELPERS =====================
def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

def get_user_data(user_id):
    user_id = str(user_id)
    if user_id not in data["users"]:
        data["users"][user_id] = {"balance": 0, "purchases": [], "username": f"User_{user_id}"}
        save_data(data)
    return data["users"][user_id]

def set_user_state(user_id, state, extra_data=None):
    user_id = str(user_id)
    data["states"][user_id] = {"state": state, "data": extra_data or {}}
    save_data(data)

def get_user_state(user_id):
    user_id = str(user_id)
    return data["states"].get(user_id, {"state": -1, "data": {}})

def clear_user_state(user_id):
    user_id = str(user_id)
    if user_id in data["states"]:
        del data["states"][user_id]
        save_data(data)

def has_used_coupon(user_id, coupon_code):
    user_id = str(user_id)
    if user_id not in data["used_coupons"]:
        data["used_coupons"][user_id] = []
    return coupon_code in data["used_coupons"][user_id]

def mark_coupon_used(user_id, coupon_code):
    user_id = str(user_id)
    if user_id not in data["used_coupons"]:
        data["used_coupons"][user_id] = []
    data["used_coupons"][user_id].append(coupon_code)
    save_data(data)

def has_used_discount(user_id, discount_code):
    user_id = str(user_id)
    if user_id not in data["used_discounts"]:
        data["used_discounts"][user_id] = []
    return discount_code in data["used_discounts"][user_id]

def mark_discount_used(user_id, discount_code):
    user_id = str(user_id)
    if user_id not in data["used_discounts"]:
        data["used_discounts"][user_id] = []
    data["used_discounts"][user_id].append(discount_code)
    save_data(data)

# ===================== QR =====================
def generate_upi_qr(amount: int) -> BytesIO:
    try:
        upi_url = f"upi://pay?pa={UPI_ID}&pn={UPI_NAME}&am={amount}&cu=INR&tn=VirtualAccountPayment"
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(upi_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        bio = BytesIO()
        bio.name = f'upi_qr_{amount}.png'
        img.save(bio, 'PNG')
        bio.seek(0)
        return bio
    except Exception as e:
        logger.error(f"[QR GENERATION ERROR] {e}")
        return None

# ===================== LOGGING =====================
async def send_log_to_support(context: ContextTypes.DEFAULT_TYPE, log_message: str):
    try:
        await context.bot.send_message(
            chat_id=SUPPORT_GROUP_ID,
            text=log_message,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"[LOG ERROR] Failed to send log: {e}")

async def log_user_registration(context, user_id, username):
    log = f"""
🆕 **NEW USER REGISTERED**

👤 **User:** {username}
🆔 **ID:** `{user_id}`
⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

📊 **Total Users:** {len(data['users'])}
"""
    await send_log_to_support(context, log)

async def log_insufficient_balance(context, user_id, username, required, current):
    log = f"""
⚠️ **INSUFFICIENT BALANCE**

👤 **User:** {username}
🆔 **ID:** `{user_id}`
💰 **Required:** {required} INR
💳 **Current:** {current} INR
❌ **Shortage:** {required - current} INR

⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
    await send_log_to_support(context, log)

async def log_payment_submitted(context, user_id, username, amount):
    log = f"""
💳 **PAYMENT SUBMITTED**

👤 **User:** {username}
🆔 **ID:** `{user_id}`
💰 **Amount:** {amount} INR
📸 **Screenshot:** Received

⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
⚠️ **Status:** Waiting for approval
"""
    await send_log_to_support(context, log)

async def log_payment_approved(context, user_id, username, amount):
    log = f"""
✅ **PAYMENT APPROVED**

👤 **User:** {username}
🆔 **ID:** `{user_id}`
💰 **Amount:** {amount} INR

⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
💳 **New Balance:** {data['users'][str(user_id)]['balance']} INR
"""
    await send_log_to_support(context, log)

async def log_payment_rejected(context, user_id, username, amount):
    log = f"""
❌ **PAYMENT REJECTED**

👤 **User:** {username}
🆔 **ID:** `{user_id}`
💰 **Amount:** {amount} INR

⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
    await send_log_to_support(context, log)

async def log_session_added(context, country, quantity, price, phone_number="N/A", twofa=None):
    twofa_line = f"\n🔐 **2FA:** `{twofa}`" if twofa else ""
    log = f"""
➕ **SESSION ADDED**

🌍 **Country:** {country.upper()}
📊 **Added:** {quantity} session(s)
💰 **Price:** {price} INR
📦 **Total Stock:** {data['accounts'][country]['quantity']}

📱 **Phone Added:** `{phone_number}`{twofa_line}

⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
    await send_log_to_support(context, log)

async def log_number_purchase(context, user_id, username, country, quantity, price, phone_numbers):
    phones_text = "\n".join([f"   • `{phone}`" for phone in phone_numbers])
    log = f"""
✅ **NUMBER SOLD - SUCCESSFUL**

👤 **Buyer:** {username}
🆔 **User ID:** `{user_id}`
🌍 **Country:** {country.upper()}
📊 **Quantity:** {quantity}
💰 **Amount:** {price} INR

📱 **Phone Numbers:**
{phones_text}

⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
💳 **Remaining Balance:** {data['users'][str(user_id)]['balance']} INR
📦 **Stock Left:** {data['accounts'][country]['quantity']}
"""
    await send_log_to_support(context, log)

async def log_otp_fetched(context, user_id, username, country, success_count, total):
    log = f"""
🔑 **OTP FETCH ATTEMPT**

👤 **User:** {username}
🆔 **ID:** `{user_id}`
🌍 **Country:** {country.upper()}
✅ **Found:** {success_count}/{total}

⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
    await send_log_to_support(context, log)

async def log_owner_balance_change(context, action, target_user_id, amount, before, after, owner_id):
    log = f"""
👑 **OWNER BALANCE UPDATE**

🧾 **Action:** `{action}`
👤 **Target User:** `{target_user_id}`
💰 **Amount:** `{amount} INR`
📉 **Before:** `{before} INR`
📈 **After:** `{after} INR`
🆔 **Owner:** `{owner_id}`

⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
    await send_log_to_support(context, log)

# ===================== PYROGRAM =====================
async def create_client(session_string, uid_tag):
    try:
        client = Client(f"temp_session_{uid_tag}", api_id=API_ID, api_hash=API_HASH, session_string=session_string)
        await client.start()
        return client
    except Exception as e:
        logger.error(f"[CLIENT ERROR] {e}")
        return None

async def get_phone_number(client):
    try:
        me = await client.get_me()
        return f"+{me.phone_number}" if me.phone_number else "N/A"
    except Exception as e:
        logger.error(f"[PHONE ERROR] {e}")
        return "Error"

async def get_otp_from_telegram(client):
    try:
        async for message in client.get_chat_history(777000, limit=15):
            if message.text and message.from_user and str(message.from_user.id) == "777000":
                patterns = [
                    r'(?:code|код)[:\s]+(\d{5,6})',
                    r'\b(\d{5,6})\b',
                ]
                for pattern in patterns:
                    otp_match = re.search(pattern, message.text, re.IGNORECASE)
                    if otp_match:
                        potential_otp = otp_match.group(1) if otp_match.groups() else otp_match.group(0)
                        if len(potential_otp) in [5, 6]:
                            if any(kw in message.text.lower() for kw in ['code', 'код', 'login', 'telegram']):
                                return potential_otp
        return None
    except Exception as e:
        logger.error(f"[OTP ERROR] {e}")
        return None

# ===================== FORCE JOIN =====================
async def check_user_membership(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    current_time = datetime.now().timestamp()

    if user_id in membership_cache:
        cache_entry = membership_cache[user_id]
        if current_time - cache_entry["time"] < CACHE_DURATION:
            return cache_entry["is_member"]

    try:
        channel_task = context.bot.get_chat_member(SUPPORT_CHANNEL_ID, user_id)
        group_task = context.bot.get_chat_member(SUPPORT_GROUP_ID, user_id)
        channel_member, group_member = await asyncio.gather(channel_task, group_task)

        channel_joined = channel_member.status in ['member', 'administrator', 'creator']
        group_joined = group_member.status in ['member', 'administrator', 'creator']
        is_member = channel_joined and group_joined

        membership_cache[user_id] = {"is_member": is_member, "time": current_time}
        return is_member
    except Exception as e:
        logger.error(f"[MEMBERSHIP CHECK ERROR] User {user_id}: {e}")
        return False

async def show_force_join_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username or "User"
    text = f"""
🔒 *Access Restricted!*

👋 *Hello {username}!*

⚠️ *To use this bot, you must join our official channel and group!*

📢 Channel: {SUPPORT_CHANNEL_LINK}
👥 Group: {SUPPORT_GROUP_LINK}

✅ Join both and press verify.
    """
    keyboard = [
        [InlineKeyboardButton("📢 Join Channel", url=SUPPORT_CHANNEL_LINK)],
        [InlineKeyboardButton("👥 Join Group", url=SUPPORT_GROUP_LINK)],
        [InlineKeyboardButton("✅ Joined - Verify Now", callback_data="verify_join")]
    ]
    markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(text, reply_markup=markup, parse_mode='Markdown')
    else:
        await update.callback_query.edit_message_text(text, reply_markup=markup, parse_mode='Markdown')

# ===================== /refresh =====================
async def refresh_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: reload DB + clear cache. Does NOT delete states/sessions/pending."""
    if not is_owner(update.effective_user.id):
        return
    global data
    try:
        data = ensure_keys(load_data())  # reload everything from disk
        membership_cache.clear()         # refresh membership cache only
        await update.message.reply_text(
            "✅ *REFRESH DONE!*\n\n"
            "• DB reloaded from JSON\n"
            "• Cache cleared\n"
            "• Sessions / pending payments / states SAFE ✅",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"[REFRESH ERROR] {e}")
        await update.message.reply_text("❌ *Refresh failed!*", parse_mode='Markdown')

# ===================== OWNER: /add /deduct =====================
async def owner_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    set_user_state(update.effective_user.id, WAITING_FOR_TARGET_USER_ID, {"mode": "add"})
    await update.message.reply_text("🆔 *UserID bhejo (balance add):*", parse_mode='Markdown')

async def owner_deduct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    set_user_state(update.effective_user.id, WAITING_FOR_TARGET_USER_ID, {"mode": "deduct"})
    await update.message.reply_text("🆔 *UserID bhejo (balance deduct):*", parse_mode='Markdown')

async def owner_handle_target_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = update.effective_user.id
    if not is_owner(owner_id):
        return ConversationHandler.END

    st = get_user_state(owner_id)
    mode = st["data"].get("mode")
    raw = update.message.text.strip()

    if not raw.isdigit():
        await update.message.reply_text("❌ *Invalid UserID (numbers only)*", parse_mode='Markdown')
        return WAITING_FOR_TARGET_USER_ID

    target_user_id = int(raw)
    target = get_user_data(target_user_id)
    bal = int(target.get("balance", 0))
    uname = target.get("username", f"User_{target_user_id}")

    set_user_state(owner_id, WAITING_FOR_TARGET_AMOUNT, {"mode": mode, "target_user_id": target_user_id})
    await update.message.reply_text(
        f"👤 *User Found*\n\n"
        f"• Username: `{uname}`\n"
        f"• ID: `{target_user_id}`\n"
        f"• Balance: `{bal} INR`\n\n"
        f"💰 *Amount batao kitna {'ADD' if mode=='add' else 'DEDUCT'} karna hai:*",
        parse_mode='Markdown'
    )
    return WAITING_FOR_TARGET_AMOUNT

async def owner_handle_target_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = update.effective_user.id
    if not is_owner(owner_id):
        return ConversationHandler.END

    st = get_user_state(owner_id)
    if st["state"] != WAITING_FOR_TARGET_AMOUNT:
        return ConversationHandler.END

    mode = st["data"].get("mode")
    target_user_id = int(st["data"]["target_user_id"])

    try:
        amt = int(update.message.text.strip())
        if amt <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ *Invalid amount (numbers only, >0)*", parse_mode='Markdown')
        return WAITING_FOR_TARGET_AMOUNT

    target = get_user_data(target_user_id)
    before = int(target.get("balance", 0))

    if mode == "deduct" and before < amt:
        await update.message.reply_text(
            f"❌ *Cannot deduct!*\n\nBalance: `{before} INR`\nDeduct asked: `{amt} INR`",
            parse_mode='Markdown'
        )
        clear_user_state(owner_id)
        return ConversationHandler.END

    after = before + amt if mode == "add" else before - amt
    target["balance"] = after
    save_data(data)

    await log_owner_balance_change(context, mode.upper(), target_user_id, amt, before, after, owner_id)

    await update.message.reply_text(
        f"✅ *Done!*\n\nUser: `{target_user_id}`\nAmount: `{amt} INR`\nNew Balance: `{after} INR`",
        parse_mode='Markdown'
    )
    clear_user_state(owner_id)
    return ConversationHandler.END

# ===================== START / MENU =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or f"User_{user_id}"

    if str(user_id) not in data["users"]:
        await log_user_registration(context, user_id, username)

    get_user_data(user_id)
    data["users"][str(user_id)]["username"] = username
    save_data(data)

    if not is_owner(user_id):
        ok = await check_user_membership(context, user_id)
        if not ok:
            await show_force_join_message(update, context)
            return

    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "User"
    bal = get_user_data(user_id)["balance"]

    clear_user_state(user_id)

    text = f"""
━━━━━━━━━━━━━━━━━━━━
🔥 *VIRTUAL ACCOUNT STORE* 🔥
━━━━━━━━━━━━━━━━━━━━

👋 *Welcome, {username}*
💰 *Balance:* `{bal} INR`

━━━━━━━━━━━━━━━━━━━━━━━━━━
✨ *𝐏ʀᴇᴍɪᴜᴍ 𝐅ᴇᴀᴛᴜʀᴇs* ✨
━━━━━━━━━━━━━━━━━━━━━━━━━━

🌍 *Multiple Countries Available*
⚡ *Instant OTP Delivery*
✅ *100% Working Sessions*
🔒 *Secure & Confidential*
💎 *Premium Quality*
🚀 *24/7 Support*

━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 *QUICK ACTIONS*
━━━━━━━━━━━━━━━━━━━━━━━━━━

Choose:
"""
    keyboard = [
        [InlineKeyboardButton("💎 BUY VIRTUAL ACCOUNTS", callback_data="virtual_accounts")],
        [InlineKeyboardButton("💳 MY BALANCE", callback_data=f"my_balance_{user_id}"),
         InlineKeyboardButton("➕ ADD FUNDS", callback_data="add_funds")],
        [InlineKeyboardButton("📞 SUPPORT", url=SUPPORT_GROUP_LINK)]
    ]
    markup = InlineKeyboardMarkup(keyboard)

    if data.get("bot_photo"):
        await context.bot.send_photo(chat_id=update.effective_chat.id, photo=data["bot_photo"], caption=text, reply_markup=markup, parse_mode='Markdown')
    else:
        if update.message:
            await update.message.reply_text(text, reply_markup=markup, parse_mode='Markdown')
        else:
            await update.callback_query.message.reply_text(text, reply_markup=markup, parse_mode='Markdown')

async def verify_join_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🔍 Verifying...")
    uid = update.effective_user.id

    if uid in membership_cache:
        del membership_cache[uid]

    if is_owner(uid):
        await show_main_menu(update, context)
        return

    ok = await check_user_membership(context, uid)
    if ok:
        await query.edit_message_text("✅ *Verified!*\nLoading menu...", parse_mode='Markdown')
        await show_main_menu(update, context)
    else:
        await show_force_join_message(update, context)

# ===================== SHOW COUNTRIES / BUY =====================
async def show_countries(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id

    if not is_owner(uid):
        ok = await check_user_membership(context, uid)
        if not ok:
            await show_force_join_message(update, context)
            return

    clear_user_state(uid)

    keyboard = []
    available = [c for c, info in data["accounts"].items() if info.get("quantity", 0) > 0]
    if not available:
        keyboard = [[InlineKeyboardButton("📭 No Accounts", callback_data="no_accounts")]]
        text = "📭 *No accounts available currently!*"
    else:
        text = "🌍 *Choose Country:*\n\n"
        for c in available:
            info = data["accounts"][c]
            keyboard.append([InlineKeyboardButton(f"💎 {c.upper()} ({info['quantity']}) - {info['price']} INR", callback_data=f"country_{c}")])
            text += f"• *{c.upper()}*: `{info['quantity']}` - `{info['price']} INR`\n"

    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def show_account_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    country = query.data.split("_")[1]

    if not is_owner(uid):
        ok = await check_user_membership(context, uid)
        if not ok:
            await show_force_join_message(update, context)
            return

    if country not in data["accounts"]:
        await query.edit_message_text("❌ *Country not found!*", parse_mode='Markdown')
        return

    info = data["accounts"][country]
    text = f"""
📱 *{country.upper()} Virtual Account*

💰 Price: `{info['price']} INR`
📊 Available: `{info['quantity']}`
💳 Your Balance: `{get_user_data(uid)['balance']} INR`
"""
    keyboard = [
        [InlineKeyboardButton("💳 BUY NUMBER", callback_data=f"buy_number_{country}")],
        [InlineKeyboardButton("🔙 Back", callback_data="virtual_accounts")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def process_buy_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    country = query.data.split("_")[2]

    if not is_owner(uid):
        ok = await check_user_membership(context, uid)
        if not ok:
            await show_force_join_message(update, context)
            return ConversationHandler.END

    info = data["accounts"][country]
    price = info["price"]
    available = info["quantity"]
    bal = get_user_data(uid)["balance"]

    text = f"""
🛒 *Purchase {country.upper()}*

📊 Available: `{available}`
💰 Price: `{price} INR each`
💳 Balance: `{bal} INR`

📝 *How many accounts? (1-{available}):*
"""
    await query.edit_message_text(text, parse_mode='Markdown')
    set_user_state(uid, WAITING_FOR_QUANTITY, {"country": country, "price": price, "available": available})
    return WAITING_FOR_QUANTITY

async def handle_quantity_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    st = get_user_state(uid)
    country = st["data"]["country"]
    price = st["data"]["price"]
    available = st["data"]["available"]

    try:
        qty = int(update.message.text.strip())
        if qty <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ *Invalid quantity!*", parse_mode='Markdown')
        return WAITING_FOR_QUANTITY

    if qty > available:
        await update.message.reply_text(f"❌ *Only {available} available!*", parse_mode='Markdown')
        return WAITING_FOR_QUANTITY

    total = price * qty
    bal = get_user_data(uid)["balance"]
    username = data["users"][str(uid)]["username"]

    if bal < total:
        await log_insufficient_balance(context, uid, username, total, bal)
        await update.message.reply_text(
            f"❌ *Insufficient Balance!*\n\nRequired: `{total} INR`\nYour Balance: `{bal} INR`",
            parse_mode='Markdown'
        )
        clear_user_state(uid)
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("✅ CONFIRM", callback_data=f"confirm_buy_{country}_{qty}")],
        [InlineKeyboardButton("❌ CANCEL", callback_data=f"country_{country}")]
    ]
    await update.message.reply_text(
        f"🛒 *Confirm Purchase*\n\nCountry: `{country.upper()}`\nQty: `{qty}`\nTotal: `{total} INR`",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )
    clear_user_state(uid)
    return ConversationHandler.END

async def confirm_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    parts = query.data.split("_")
    country = parts[2]
    qty = int(parts[3])

    info = data["accounts"][country]
    total = info["price"] * qty
    bal = get_user_data(uid)["balance"]

    if bal < total or info["quantity"] < qty or len(info.get("sessions", [])) < qty:
        await query.answer("❌ Not possible!", show_alert=True)
        return

    sessions = info["sessions"]
    purchased = sessions[:qty]
    info["sessions"] = sessions[qty:]
    info["quantity"] -= qty

    data["users"][str(uid)]["balance"] -= total
    purchase = {
        "country": country,
        "quantity": qty,
        "price": total,
        "sessions": purchased,
        "timestamp": datetime.now().isoformat(),
        "status": "completed"
    }
    data["users"][str(uid)]["purchases"].append(purchase)
    save_data(data)

    async def fetch_phone_for_log(session_data):
        s = session_data.get("session")
        if not s:
            return "N/A"
        try:
            client = await create_client(s, f"{uid}_log")
            if client:
                ph = await get_phone_number(client)
                await client.stop()
                return ph
        except:
            pass
        return "Error"

    phone_numbers = []
    for sd in purchased:
        phone_numbers.append(await fetch_phone_for_log(sd))

    await log_number_purchase(context, uid, data["users"][str(uid)]["username"], country, qty, total, phone_numbers)

    keyboard = [
        [InlineKeyboardButton("📱 GET NUMBER", callback_data=f"get_number_{uid}_{len(data['users'][str(uid)]['purchases'])-1}")],
        [InlineKeyboardButton("🛒 Buy More", callback_data="virtual_accounts")]
    ]
    await query.edit_message_text(
        f"🎉 *Purchase Successful!*\n\n✅ `{qty}` account(s)\n💰 Deducted: `{total} INR`\n💳 Balance: `{data['users'][str(uid)]['balance']} INR`",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def get_number_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("📱 Fetching...")

    parts = query.data.split("_")
    uid = int(parts[2])
    idx = int(parts[3])

    purchases = data["users"][str(uid)]["purchases"]
    if idx >= len(purchases):
        await query.answer("❌ Purchase not found!", show_alert=True)
        return

    purchase = purchases[idx]
    sessions = purchase.get("sessions", [])

    async def fetch_phone(i, sd):
        s = sd.get("session")
        if not s:
            return "N/A"
        try:
            client = await create_client(s, f"{uid}_{i}")
            if client:
                ph = await get_phone_number(client)
                await client.stop()
                return ph
        except:
            pass
        return "Error"

    phones = await asyncio.gather(*[fetch_phone(i, sd) for i, sd in enumerate(sessions)])

    for i, ph in enumerate(phones):
        purchase["sessions"][i]["phone_number"] = ph
    save_data(data)

    text = f"📱 *Phone Numbers Retrieved!*\n\nCountry: `{purchase['country'].upper()}`\nQty: `{purchase['quantity']}`\n"
    for i, ph in enumerate(phones, 1):
        text += f"\n*Account {i}:*\n📞 `{ph}`\n"

    keyboard = [
        [InlineKeyboardButton("🔍 GET OTP", callback_data=f"get_otp_{uid}_{idx}")],
        [InlineKeyboardButton("✅ LOGIN COMPLETE", callback_data=f"login_complete_{uid}")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def get_otp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🔍 Searching OTP...")

    parts = query.data.split("_")
    uid = int(parts[2])
    idx = int(parts[3])

    purchases = data["users"][str(uid)]["purchases"]
    if idx >= len(purchases):
        await query.answer("❌ Purchase not found!", show_alert=True)
        return

    purchase = purchases[idx]
    sessions = purchase.get("sessions", [])
    country = purchase.get("country", "Unknown")
    username = data["users"][str(uid)]["username"]

    await query.edit_message_text("⏳ *Checking 777000...*\nStart login then try.", parse_mode='Markdown')

    async def fetch_otp(i, sd):
        s = sd.get("session")
        phone = sd.get("phone_number", "N/A")
        twofa = sd.get("twofa")
        if not s:
            return {"status": "error", "message": "❌ No session", "otp": None}

        client = None
        try:
            client = await create_client(s, f"{uid}_{i}_otp")
            if client:
                if phone in ["N/A", None, "Error"]:
                    try:
                        phone = await get_phone_number(client)
                    except:
                        phone = "N/A"

                otp = await get_otp_from_telegram(client)
                await client.stop()

                if otp:
                    msg = f"✅ otp fetch - `{otp}` `{phone}`"
                    if twofa:
                        msg += f"\n🔐 2FA: `{twofa}`"
                    return {"status": "success", "message": msg, "otp": otp}
                return {"status": "not_found", "message": "⏳ OTP not found yet", "otp": None}
        except Exception as e:
            if client:
                try:
                    await client.stop()
                except:
                    pass
            return {"status": "error", "message": f"❌ Error: {str(e)[:25]}", "otp": None}

    results = await asyncio.gather(*[fetch_otp(i, sd) for i, sd in enumerate(sessions)])

    text = f"🔑 *OTP Results*\n\nCountry: `{country.upper()}`\nQty: `{purchase['quantity']}`\n"
    success = 0
    for i, r in enumerate(results, 1):
        text += f"\n*Account {i}:*\n{r['message']}\n"
        if r["status"] == "success":
            success += 1

    await log_otp_fetched(context, uid, username, country, success, len(sessions))

    keyboard = [
        [InlineKeyboardButton("🔄 TRY AGAIN", callback_data=f"get_otp_{uid}_{idx}")],
        [InlineKeyboardButton("✅ LOGIN COMPLETE", callback_data=f"login_complete_{uid}")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def login_complete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("✅ Verified!")
    keyboard = [
        [InlineKeyboardButton("🛒 Buy More", callback_data="virtual_accounts")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ]
    await query.edit_message_text("🎉 *Login Complete!*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# ===================== BALANCE =====================
async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = int(query.data.split("_")[2])

    if not is_owner(uid):
        ok = await check_user_membership(context, uid)
        if not ok:
            await show_force_join_message(update, context)
            return

    bal = get_user_data(uid)["balance"]
    text = f"💳 *My Balance*\n\n💰 Balance: `{bal} INR`"
    keyboard = [
        [InlineKeyboardButton("➕ Add Funds", callback_data="add_funds")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# ===================== ADD FUNDS =====================
async def show_add_funds_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id

    if not is_owner(uid):
        ok = await check_user_membership(context, uid)
        if not ok:
            await show_force_join_message(update, context)
            return

    clear_user_state(uid)

    text = "➕ *Add Funds*\n\nChoose method:"
    keyboard = [
        [InlineKeyboardButton("💸 Buy Funds (UPI)", callback_data="buy_fund")],
        [InlineKeyboardButton("🎟 Coupon Code", callback_data="coupon_code")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def ask_fund_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = update.effective_user.id
    await query.edit_message_text("💰 *Enter amount (min 10):*", parse_mode='Markdown')
    set_user_state(uid, WAITING_FOR_AMOUNT)
    return WAITING_FOR_AMOUNT

async def handle_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        amt = int(update.message.text.strip())
        if amt < 10:
            await update.message.reply_text("❌ *Minimum 10 INR!*", parse_mode='Markdown')
            return WAITING_FOR_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ *Numbers only!*", parse_mode='Markdown')
        return WAITING_FOR_AMOUNT

    data["pending_payments"][str(uid)] = {
        "amount": amt,
        "timestamp": datetime.now().isoformat(),
        "status": "waiting_screenshot"
    }
    save_data(data)

    qr = generate_upi_qr(amt)
    text = f"""
💸 *Payment Details*

💰 Amount: `{amt} INR`
👤 UPI ID: `{UPI_ID}`

📸 Payment karne ke baad *screenshot yahin bhejo*.
"""
    if qr:
        await update.message.reply_photo(photo=qr, caption=text, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, parse_mode='Markdown')

    set_user_state(uid, WAITING_FOR_SCREENSHOT, {"amount": amt})
    return WAITING_FOR_SCREENSHOT

# ===================== ✅ SCREENSHOT HANDLER (100% FIX) =====================
async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User confirmation + owner approve/reject buttons 100%"""
    uid = update.effective_user.id
    st = get_user_state(uid)
    username = data["users"].get(str(uid), {}).get("username", f"User_{uid}")

    if st["state"] != WAITING_FOR_SCREENSHOT:
        await update.message.reply_text("❌ *No pending payment.*", parse_mode='Markdown')
        return ConversationHandler.END

    amount = int(st["data"].get("amount", 0))

    # Accept: photo OR image document
    file_id = None
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    elif update.message.document and update.message.document.mime_type and update.message.document.mime_type.startswith("image/"):
        file_id = update.message.document.file_id

    if not file_id:
        await update.message.reply_text("❌ *Valid screenshot bhejo (image).*", parse_mode='Markdown')
        return WAITING_FOR_SCREENSHOT

    # Log submitted
    await log_payment_submitted(context, uid, username, amount)

    # ✅ 1) ALWAYS tell user screenshot received
    bal_btn = [[InlineKeyboardButton("💳 Check Balance", callback_data=f"my_balance_{uid}")]]
    await update.message.reply_text(
        "✅ *Screenshot bhej diya gaya hai!*\n\n"
        "🔄 *Owner verify karega 5-10 min me.*\n"
        "⏳ *Approval ke baad balance update ho jayega.*",
        reply_markup=InlineKeyboardMarkup(bal_btn),
        parse_mode='Markdown'
    )

    # Save pending payment
    data["pending_payments"][str(uid)] = {
        "amount": amount,
        "screenshot": file_id,
        "timestamp": datetime.now().isoformat(),
        "status": "submitted"
    }
    save_data(data)

    # ✅ 2) ALWAYS send owner photo WITH buttons (NO dependency on forward)
    owner_caption = (
        f"🔔 *New Payment!*\n\n"
        f"👤 User: `{username}`\n"
        f"🆔 ID: `{uid}`\n"
        f"💰 Amount: `{amount} INR`\n"
        f"⏰ Time: `{datetime.now().strftime('%H:%M %d/%m')}`\n\n"
        f"🔍 *Approve/Reject:*"
    )
    owner_kb = [
        [InlineKeyboardButton("✅ APPROVE", callback_data=f"approve_fund_{uid}_{amount}")],
        [InlineKeyboardButton("❌ REJECT", callback_data=f"reject_fund_{uid}")]
    ]
    try:
        await context.bot.send_photo(
            chat_id=OWNER_ID,
            photo=file_id,
            caption=owner_caption,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(owner_kb)
        )
    except Exception as e:
        logger.error(f"[OWNER PHOTO SEND ERROR] {e}")
        # fallback: send message with buttons
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=owner_caption + "\n\n❌ Screenshot photo send failed (check bot permissions).",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(owner_kb)
        )

    clear_user_state(uid)
    return ConversationHandler.END

# ===================== OWNER APPROVE/REJECT =====================
async def approve_fund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("✅ Approved!")

    if not is_owner(update.effective_user.id):
        return

    parts = query.data.split("_")
    uid = int(parts[2])
    amount = int(parts[3])

    username = data["users"].get(str(uid), {}).get("username", f"User_{uid}")
    get_user_data(uid)["balance"] += amount
    save_data(data)

    if str(uid) in data["pending_payments"]:
        data["pending_payments"][str(uid)]["status"] = "approved"
        save_data(data)

    await log_payment_approved(context, uid, username, amount)

    kb = [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
    try:
        await context.bot.send_message(
            chat_id=uid,
            text=f"🎉 *Funds Added!*\n\n💰 Amount: `{amount} INR`\n💳 Balance: `{get_user_data(uid)['balance']} INR`",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(kb)
        )
    except Exception as e:
        logger.error(f"[USER NOTIFY ERROR] {e}")

    await query.edit_message_caption(caption=f"✅ *Approved {amount} INR for user {uid}*", parse_mode='Markdown')

async def reject_fund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("❌ Rejected!")

    if not is_owner(update.effective_user.id):
        return

    uid = int(query.data.split("_")[2])
    username = data["users"].get(str(uid), {}).get("username", f"User_{uid}")
    amount = int(data["pending_payments"].get(str(uid), {}).get("amount", 0))

    await log_payment_rejected(context, uid, username, amount)

    try:
        await context.bot.send_message(
            chat_id=uid,
            text="❌ *Payment Rejected!*\n\n💡 *Try again with correct screenshot/amount.*",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"[USER NOTIFY ERROR] {e}")

    if str(uid) in data["pending_payments"]:
        data["pending_payments"][str(uid)]["status"] = "rejected"
        save_data(data)

    try:
        await query.edit_message_caption(caption=f"❌ *Rejected user {uid}*", parse_mode='Markdown')
    except:
        await query.edit_message_text(f"❌ *Rejected user {uid}*", parse_mode='Markdown')

# ===================== OWNER PANEL + SESSION ADD (2FA) =====================
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        if update.message:
            await update.message.reply_text("❌ *Unauthorized!*", parse_mode='Markdown')
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("➕ Add Number", callback_data="owner_addnumber")],
        [InlineKeyboardButton("🏠 Close", callback_data="main_menu")]
    ]
    text = "🔧 *Owner Panel*"
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def owner_add_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END

    await query.edit_message_text("➕ *Enter country name:*", parse_mode='Markdown')
    set_user_state(update.effective_user.id, WAITING_FOR_COUNTRY)
    return WAITING_FOR_COUNTRY

async def handle_country_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END

    country = update.message.text.strip().upper()
    if country not in data["accounts"]:
        data["accounts"][country] = {"price": 0, "quantity": 0, "sessions": []}
        save_data(data)

    set_user_state(update.effective_user.id, WAITING_FOR_PRICE, {"country": country})
    await update.message.reply_text(f"💰 *Set price for {country} (INR):*", parse_mode='Markdown')
    return WAITING_FOR_PRICE

async def handle_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END

    st = get_user_state(update.effective_user.id)
    country = st["data"]["country"]

    try:
        price = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ *Numbers only!*", parse_mode='Markdown')
        return WAITING_FOR_PRICE

    data["accounts"][country]["price"] = price
    save_data(data)

    set_user_state(update.effective_user.id, WAITING_FOR_SESSION, {"country": country, "price": price})
    await update.message.reply_text("🔗 *Send session string:*", parse_mode='Markdown')
    return WAITING_FOR_SESSION

async def handle_session_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END

    text = update.message.text.strip()
    st = get_user_state(update.effective_user.id)
    country = st["data"]["country"]
    price = st["data"]["price"]

    if text == "/skip":
        clear_user_state(update.effective_user.id)
        await update.message.reply_text(f"✅ *Completed for {country}*", parse_mode='Markdown')
        return ConversationHandler.END

    if len(text) < 50:
        await update.message.reply_text("❌ *Session too short!*", parse_mode='Markdown')
        return WAITING_FOR_SESSION

    set_user_state(update.effective_user.id, WAITING_FOR_2FA, {"country": country, "price": price, "pending_session": text})
    await update.message.reply_text(
        "🔐 *2FA hai?*\n\n✅ 2FA hai to password bhejo\n❌ nahi to `/skip`",
        parse_mode='Markdown'
    )
    return WAITING_FOR_2FA

async def handle_2fa_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END

    st = get_user_state(update.effective_user.id)
    country = st["data"]["country"]
    price = st["data"]["price"]
    session_string = st["data"]["pending_session"]

    msg = update.message.text.strip()
    twofa = None if msg == "/skip" else msg

    phone_number = "N/A"
    try:
        client = await create_client(session_string, f"owner_add_{country}_{int(datetime.now().timestamp())}")
        if client:
            phone_number = await get_phone_number(client)
            await client.stop()
    except Exception as e:
        logger.error(f"[SESSION PHONE FETCH ERROR] {e}")

    session_data = {
        "session": session_string,
        "added": datetime.now().isoformat(),
        "twofa": twofa,
        "phone_number": phone_number
    }
    data["accounts"][country]["sessions"].append(session_data)
    data["accounts"][country]["quantity"] += 1
    save_data(data)

    await log_session_added(context, country, 1, price, phone_number=phone_number, twofa=twofa)

    await update.message.reply_text(
        f"✅ *Added!*\n\nCountry: `{country}`\nPhone: `{phone_number}`\nTotal: `{data['accounts'][country]['quantity']}`\n\n"
        f"Add another session OR `/skip` to finish.",
        parse_mode='Markdown'
    )

    set_user_state(update.effective_user.id, WAITING_FOR_SESSION, {"country": country, "price": price})
    return WAITING_FOR_SESSION

# ===================== BUTTON HANDLER =====================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = update.effective_user.id
    data_str = query.data

    try:
        if data_str == "verify_join":
            await verify_join_handler(update, context)
            return

        if not is_owner(uid):
            ok = await check_user_membership(context, uid)
            if not ok:
                await query.answer("⚠️ Join first!", show_alert=True)
                await show_force_join_message(update, context)
                return

        await query.answer()

        if data_str == "main_menu":
            await show_main_menu(update, context)
        elif data_str == "virtual_accounts":
            await show_countries(update, context)
        elif data_str.startswith("country_"):
            await show_account_details(update, context)
        elif data_str.startswith("buy_number_"):
            return await process_buy_number(update, context)
        elif data_str.startswith("confirm_buy_"):
            await confirm_purchase(update, context)
        elif data_str.startswith("get_number_"):
            await get_number_handler(update, context)
        elif data_str.startswith("get_otp_"):
            await get_otp_handler(update, context)
        elif data_str.startswith("login_complete_"):
            await login_complete(update, context)
        elif data_str.startswith("my_balance_"):
            await show_balance(update, context)
        elif data_str == "add_funds":
            await show_add_funds_options(update, context)
        elif data_str == "buy_fund":
            return await ask_fund_amount(update, context)
        elif data_str == "no_accounts":
            await query.edit_message_text("📭 *No Accounts Available*", parse_mode='Markdown')
        elif data_str == "owner_panel":
            await owner_panel(update, context)
        elif data_str == "owner_addnumber":
            return await owner_add_number(update, context)
        elif data_str.startswith("approve_fund_"):
            await approve_fund(update, context)
        elif data_str.startswith("reject_fund_"):
            await reject_fund(update, context)
        else:
            await query.answer("⚠️ Unknown action!", show_alert=True)

    except Exception as e:
        logger.error(f"[BUTTON ERROR] {type(e).__name__}('{str(e)}')")
        try:
            await query.answer("❌ Error occurred! Try again by /start", show_alert=True)
        except:
            pass

# ===================== GLOBAL FALLBACK =====================
async def global_text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    st = get_user_state(uid)
    state = st["state"]

    if state == WAITING_FOR_TARGET_USER_ID:
        return await owner_handle_target_user_id(update, context)
    if state == WAITING_FOR_TARGET_AMOUNT:
        return await owner_handle_target_amount(update, context)

    if state == WAITING_FOR_AMOUNT:
        return await handle_amount_input(update, context)
    if state == WAITING_FOR_SCREENSHOT:
        # If user sends text while waiting screenshot
        await update.message.reply_text("📸 *Payment screenshot bhejo (image).*", parse_mode='Markdown')
        return WAITING_FOR_SCREENSHOT
    if state == WAITING_FOR_COUNTRY:
        return await handle_country_input(update, context)
    if state == WAITING_FOR_PRICE:
        return await handle_price_input(update, context)
    if state == WAITING_FOR_SESSION:
        return await handle_session_input(update, context)
    if state == WAITING_FOR_2FA:
        return await handle_2fa_input(update, context)
    if state == WAITING_FOR_QUANTITY:
        return await handle_quantity_input(update, context)

    await update.message.reply_text("Use /start", parse_mode='Markdown')
    return ConversationHandler.END

# ===================== ERROR HANDLER =====================
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text("❌ *Error occurred! Try /start*", parse_mode='Markdown')
        except:
            pass

# ===================== CONVERSATION HANDLER =====================
def get_conversation_handler():
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("panel", owner_panel),
            CommandHandler("add", owner_add_command),
            CommandHandler("deduct", owner_deduct_command),
            CommandHandler("refresh", refresh_command),  # ✅ NEW
            CallbackQueryHandler(button_handler)
        ],
        states={
            WAITING_FOR_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount_input)],

            # ✅ screenshot accept PHOTO + IMAGE DOCUMENT
            WAITING_FOR_SCREENSHOT: [
                MessageHandler(filters.PHOTO, handle_screenshot),
                MessageHandler(filters.Document.IMAGE, handle_screenshot),
            ],

            WAITING_FOR_COUNTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_country_input)],
            WAITING_FOR_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_price_input)],
            WAITING_FOR_SESSION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_session_input)],
            WAITING_FOR_2FA: [MessageHandler(filters.TEXT, handle_2fa_input)],
            WAITING_FOR_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quantity_input)],

            WAITING_FOR_TARGET_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, owner_handle_target_user_id)],
            WAITING_FOR_TARGET_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, owner_handle_target_amount)],
        },
        fallbacks=[
            CommandHandler("start", start),
            CallbackQueryHandler(button_handler)
        ],
        allow_reentry=True,
        per_user=True,
        per_chat=True
    )

# ===================== MAIN =====================
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(get_conversation_handler())

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_text_fallback))

    application.add_error_handler(error_handler)

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🔥 VIRTUAL ACCOUNT BOT - 100% FIXED 🔥")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"👑 Owner: {OWNER_ID}")
    print("✅ Screenshot confirm fixed")
    print("✅ Owner approve/reject buttons fixed")
    print("✅ /refresh added (no data loss)")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main()
