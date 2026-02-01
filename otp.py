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

# Configuration
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

# Conversation States
(
    WAITING_FOR_AMOUNT,
    WAITING_FOR_COUPON,
    WAITING_FOR_SCREENSHOT,
    WAITING_FOR_COUNTRY,
    WAITING_FOR_PRICE,
    WAITING_FOR_SESSION,
    WAITING_FOR_DISCOUNT_AMOUNT,
    WAITING_FOR_COUPON_AMOUNT,
    WAITING_FOR_2FA,                 # USED NOW
    WAITING_FOR_LOGIN_STATUS,
    WAITING_FOR_DISCOUNT_CODE,
    WAITING_FOR_BOT_PHOTO,
    WAITING_FOR_QUANTITY,
    WAITING_FOR_ADD_MORE_SESSIONS,
    WAITING_FOR_BROADCAST_MESSAGE,
    WAITING_FOR_TARGET_USER_ID,      # NEW: /add /deduct
    WAITING_FOR_TARGET_AMOUNT        # NEW: /add /deduct
) = range(17)

# Load/Save Database
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

def save_data(data):
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=2)

data = load_data()

# Initialize data structures
for key in ["users", "accounts", "discount_codes", "coupons", "pending_payments", "states", "used_coupons", "used_discounts"]:
    if key not in data:
        data[key] = {}

# ============ QR CODE GENERATION ============
def generate_upi_qr(amount: int) -> BytesIO:
    """Generate UPI QR code with dynamic amount"""
    try:
        upi_url = f"upi://pay?pa={UPI_ID}&pn={UPI_NAME}&am={amount}&cu=INR&tn=VirtualAccountPayment"

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
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

# ============ LOGGING SYSTEM ============
async def send_log_to_support(context: ContextTypes.DEFAULT_TYPE, log_message: str):
    """Send detailed logs to support group"""
    try:
        await context.bot.send_message(
            chat_id=SUPPORT_GROUP_ID,
            text=log_message,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"[LOG ERROR] Failed to send log: {e}")

async def log_user_registration(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str):
    log = f"""
🆕 **NEW USER REGISTERED**

👤 **User:** {username}
🆔 **ID:** `{user_id}`
⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}

📊 **Total Users:** {len(data['users'])}
"""
    await send_log_to_support(context, log)

async def log_number_purchase(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, country: str, quantity: int, price: int, phone_numbers: list):
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

async def log_session_added(context: ContextTypes.DEFAULT_TYPE, country: str, quantity: int, price: int, phone_number: str = "N/A", twofa: str = None):
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

async def log_country_deleted(context: ContextTypes.DEFAULT_TYPE, country: str, quantity: int, price: int):
    log = f"""
🗑️ **COUNTRY DELETED**

🌍 **Country:** {country.upper()}
📊 **Removed:** {quantity} session(s)
💰 **Price:** {price} INR

⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
    await send_log_to_support(context, log)

async def log_coupon_redeemed(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, coupon_code: str, amount: int):
    log = f"""
🎟️ **COUPON REDEEMED**

👤 **User:** {username}
🆔 **ID:** `{user_id}`
🎫 **Coupon:** `{coupon_code}`
💰 **Amount:** {amount} INR

⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
💳 **New Balance:** {data['users'][str(user_id)]['balance']} INR
"""
    await send_log_to_support(context, log)

async def log_discount_applied(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, discount_code: str, discount: int):
    log = f"""
🎟️ **DISCOUNT CODE APPLIED**

👤 **User:** {username}
🆔 **ID:** `{user_id}`
🏷️ **Code:** `{discount_code}`
💰 **Discount:** {discount} INR

⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
    await send_log_to_support(context, log)

async def log_payment_submitted(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, amount: int):
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

async def log_payment_approved(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, amount: int):
    log = f"""
✅ **PAYMENT APPROVED**

👤 **User:** {username}
🆔 **ID:** `{user_id}`
💰 **Amount:** {amount} INR

⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
💳 **New Balance:** {data['users'][str(user_id)]['balance']} INR
"""
    await send_log_to_support(context, log)

async def log_payment_rejected(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, amount: int):
    log = f"""
❌ **PAYMENT REJECTED**

👤 **User:** {username}
🆔 **ID:** `{user_id}`
💰 **Amount:** {amount} INR

⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
    await send_log_to_support(context, log)

async def log_coupon_created(context: ContextTypes.DEFAULT_TYPE, coupon_code: str, amount: int):
    log = f"""
🎫 **NEW COUPON CREATED**

🎟️ **Code:** `{coupon_code}`
💰 **Amount:** {amount} INR
📊 **Usage:** One-time per user

⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
    await send_log_to_support(context, log)

async def log_discount_created(context: ContextTypes.DEFAULT_TYPE, discount_code: str, discount: int):
    log = f"""
🏷️ **NEW DISCOUNT CREATED**

🎟️ **Code:** `{discount_code}`
💰 **Discount:** {discount} INR
📊 **Usage:** One-time per user

⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
    await send_log_to_support(context, log)

async def log_broadcast_sent(context: ContextTypes.DEFAULT_TYPE, total: int, success: int, failed: int):
    log = f"""
📣 **BROADCAST COMPLETED**

👥 **Total Users:** {total}
✅ **Sent:** {success}
❌ **Failed:** {failed}
📊 **Success Rate:** {(success/total*100):.1f}%

⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
    await send_log_to_support(context, log)

async def log_otp_fetched(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, country: str, success_count: int, total: int):
    log = f"""
🔑 **OTP FETCH ATTEMPT**

👤 **User:** {username}
🆔 **ID:** `{user_id}`
🌍 **Country:** {country.upper()}
✅ **Found:** {success_count}/{total}

⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
"""
    await send_log_to_support(context, log)

async def log_insufficient_balance(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, required: int, current: int):
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

async def log_owner_balance_change(context: ContextTypes.DEFAULT_TYPE, action: str, target_user_id: int, amount: int, before: int, after: int, owner_id: int):
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

# Helper Functions
def get_user_data(user_id):
    user_id = str(user_id)
    if user_id not in data["users"]:
        data["users"][user_id] = {"balance": 0, "purchases": [], "username": f"User_{user_id}"}
        save_data(data)
    return data["users"][user_id]

def is_owner(user_id):
    return user_id == OWNER_ID

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

# SPEED OPTIMIZED: Membership check with 1-hour cache
async def check_user_membership(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    """Check if user is member with 1-hour cache"""
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

        membership_cache[user_id] = {
            "is_member": is_member,
            "time": current_time
        }

        return is_member
    except Exception as e:
        logger.error(f"[MEMBERSHIP CHECK ERROR] User {user_id}: {e}")
        return False

async def show_force_join_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show force join message"""
    username = update.effective_user.username or "User"

    text = f"""
🔒 *Access Restricted!*

👋 *Hello {username}!*

⚠️ *To use this bot, you must join our official channel and group:*

📢 *Support Channel:* Updates & Announcements
👥 *Support Group:* Help & Community

🔐 *After joining both, click "✅ Joined" button!*

💡 *Why join?*
• Get latest updates & offers
• 24/7 community support
• Exclusive deals for members
    """

    keyboard = [
        [InlineKeyboardButton("📢 Join Channel", url=SUPPORT_CHANNEL_LINK)],
        [InlineKeyboardButton("👥 Join Group", url=SUPPORT_GROUP_LINK)],
        [InlineKeyboardButton("✅ Joined - Verify Now", callback_data="verify_join")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# Pyrogram Functions
async def create_client(session_string, user_id):
    """Create Pyrogram client"""
    try:
        client = Client(
            f"temp_session_{user_id}",
            api_id=API_ID,
            api_hash=API_HASH,
            session_string=session_string
        )
        await client.start()
        return client
    except Exception as e:
        logger.error(f"[CLIENT ERROR] {e}")
        return None

async def get_phone_number(client):
    """Get phone number"""
    try:
        me = await client.get_me()
        return f"+{me.phone_number}" if me.phone_number else "N/A"
    except Exception as e:
        logger.error(f"[PHONE ERROR] {e}")
        return "Error"

async def get_otp_from_telegram(client):
    """Fetch OTP from Telegram (777000)"""
    try:
        async for message in client.get_chat_history(777000, limit=15):
            if message.text and message.from_user:
                if str(message.from_user.id) == "777000":
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

# ===================== OWNER: /add & /deduct =====================
async def owner_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return

    clear_user_state(user_id)
    set_user_state(user_id, WAITING_FOR_TARGET_USER_ID, {"mode": "add"})
    await update.message.reply_text(
        "🆔 *UserID bhejo jiska balance add karna hai:*\n\nExample: `123456789`",
        parse_mode='Markdown'
    )

async def owner_deduct_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return

    clear_user_state(user_id)
    set_user_state(user_id, WAITING_FOR_TARGET_USER_ID, {"mode": "deduct"})
    await update.message.reply_text(
        "🆔 *UserID bhejo jiska balance deduct karna hai:*\n\nExample: `123456789`",
        parse_mode='Markdown'
    )

async def owner_handle_target_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = update.effective_user.id
    if not is_owner(owner_id):
        return ConversationHandler.END

    state = get_user_state(owner_id)
    mode = state["data"].get("mode")
    raw = update.message.text.strip()

    if not raw.isdigit():
        await update.message.reply_text("❌ *Invalid UserID! Sirf numbers.*", parse_mode='Markdown')
        return WAITING_FOR_TARGET_USER_ID

    target_user_id = int(raw)
    target = get_user_data(target_user_id)
    target_username = target.get("username", f"User_{target_user_id}")
    bal = target.get("balance", 0)

    set_user_state(owner_id, WAITING_FOR_TARGET_AMOUNT, {"mode": mode, "target_user_id": target_user_id})

    await update.message.reply_text(
        f"👤 *User Found*\n\n"
        f"• Username: `{target_username}`\n"
        f"• UserID: `{target_user_id}`\n"
        f"• Balance: `{bal} INR`\n\n"
        f"💰 *Amount batao kitna {'ADD' if mode=='add' else 'DEDUCT'} karna hai:*",
        parse_mode='Markdown'
    )
    return WAITING_FOR_TARGET_AMOUNT

async def owner_handle_target_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    owner_id = update.effective_user.id
    if not is_owner(owner_id):
        return ConversationHandler.END

    state = get_user_state(owner_id)
    if state["state"] != WAITING_FOR_TARGET_AMOUNT:
        return ConversationHandler.END

    mode = state["data"].get("mode")
    target_user_id = int(state["data"].get("target_user_id"))
    raw = update.message.text.strip()

    try:
        amt = int(raw)
        if amt <= 0:
            await update.message.reply_text("❌ *Amount 1 se bada hona chahiye.*", parse_mode='Markdown')
            return WAITING_FOR_TARGET_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ *Invalid amount! Numbers only.*", parse_mode='Markdown')
        return WAITING_FOR_TARGET_AMOUNT

    target = get_user_data(target_user_id)
    before = int(target.get("balance", 0))

    if mode == "add":
        after = before + amt
        target["balance"] = after
        save_data(data)
        await log_owner_balance_change(context, "ADD", target_user_id, amt, before, after, owner_id)
        await update.message.reply_text(
            f"✅ *Done!*\n\n"
            f"👤 `{target_user_id}`\n"
            f"➕ Added: `{amt} INR`\n"
            f"💳 New Balance: `{after} INR`",
            parse_mode='Markdown'
        )
    else:
        if before < amt:
            await update.message.reply_text(
                f"❌ *Cannot deduct!* User balance kam hai.\n\n"
                f"💳 Balance: `{before} INR`\n"
                f"📉 Deduct asked: `{amt} INR`",
                parse_mode='Markdown'
            )
            return ConversationHandler.END

        after = before - amt
        target["balance"] = after
        save_data(data)
        await log_owner_balance_change(context, "DEDUCT", target_user_id, amt, before, after, owner_id)
        await update.message.reply_text(
            f"✅ *Done!*\n\n"
            f"👤 `{target_user_id}`\n"
            f"➖ Deducted: `{amt} INR`\n"
            f"💳 New Balance: `{after} INR`",
            parse_mode='Markdown'
        )

    clear_user_state(owner_id)
    return ConversationHandler.END

# Welcome & Main Functions
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or f"User_{user_id}"

    if str(user_id) not in data["users"]:
        await log_user_registration(context, user_id, username)

    if is_owner(user_id):
        await show_main_menu(update, context)
        return

    is_member = await check_user_membership(context, user_id)
    if not is_member:
        await show_force_join_message(update, context)
        return

    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show main menu"""
    user_id = update.effective_user.id
    username = update.effective_user.username or "User"

    get_user_data(user_id)
    data["users"][str(user_id)]["username"] = username
    save_data(data)

    clear_user_state(user_id)

    welcome_text = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━
🔥 *VIRTUAL ACCOUNT STORE* 🔥
━━━━━━━━━━━━━━━━━━━━━━━━━━

👋 *Welcome Back, {username}!*

💰 *Balance:* `{get_user_data(user_id)['balance']} INR`

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
    """

    keyboard = [
        [InlineKeyboardButton("💎 BUY VIRTUAL ACCOUNTS", callback_data="virtual_accounts")],
        [InlineKeyboardButton("💳 MY BALANCE", callback_data=f"my_balance_{user_id}"),
         InlineKeyboardButton("➕ ADD FUNDS", callback_data="add_funds")],
        [InlineKeyboardButton("📞 SUPPORT", url=SUPPORT_GROUP_LINK)]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    if data.get("bot_photo"):
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=data["bot_photo"],
            caption=welcome_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        if update.message:
            await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')
        elif update.callback_query:
            await update.callback_query.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

# Verify Join Handler
async def verify_join_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle verification"""
    query = update.callback_query
    await query.answer("🔍 Verifying...")
    user_id = update.effective_user.id

    if is_owner(user_id):
        await show_main_menu(update, context)
        return

    if user_id in membership_cache:
        del membership_cache[user_id]

    is_member = await check_user_membership(context, user_id)

    if is_member:
        success_text = """
✅ *Verification Successful!*

🎉 *Welcome to Virtual Account Store!*

🚀 *Loading main menu...*
        """
        await query.edit_message_text(success_text, parse_mode='Markdown')
        await show_main_menu(update, context)
    else:
        error_text = """
❌ *Verification Failed!*

⚠️ *You must join both channel and group!*
        """

        keyboard = [
            [InlineKeyboardButton("📢 Join Channel", url=SUPPORT_CHANNEL_LINK)],
            [InlineKeyboardButton("👥 Join Group", url=SUPPORT_GROUP_LINK)],
            [InlineKeyboardButton("✅ Joined - Verify Now", callback_data="verify_join")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(error_text, reply_markup=reply_markup, parse_mode='Markdown')

# Main Menu Navigation
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if not is_owner(user_id):
        is_member = await check_user_membership(context, user_id)
        if not is_member:
            await show_force_join_message(update, context)
            return

    clear_user_state(user_id)

    keyboard = [
        [InlineKeyboardButton("💎 VIRTUAL ACCOUNTS", callback_data="virtual_accounts")],
        [InlineKeyboardButton("💳 MY BALANCE", callback_data=f"my_balance_{user_id}")],
        [InlineKeyboardButton("➕ ADD FUNDS", callback_data="add_funds")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_text = f"""
🔥 *Welcome Back!*

💰 *Your Balance:* `{get_user_data(user_id)['balance']} INR`

🎯 *Choose an option:*
    """

    await query.edit_message_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

# Virtual Accounts Flow
async def show_countries(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if not is_owner(user_id):
        is_member = await check_user_membership(context, user_id)
        if not is_member:
            await show_force_join_message(update, context)
            return

    clear_user_state(user_id)

    countries = []
    keyboard = []

    for country, info in data["accounts"].items():
        if info.get("quantity", 0) > 0:
            countries.append(country)
            keyboard.append([InlineKeyboardButton(
                f"💎 {country.upper()} ({info['quantity']} available) - {info['price']} INR",
                callback_data=f"country_{country}"
            )])

    if not countries:
        keyboard = [[InlineKeyboardButton("📭 No Accounts", callback_data="no_accounts")]]
        text = "📭 *No accounts available currently!*"
    else:
        text = "🌍 *Choose Country:*\n\n" + \
               "\n".join([f"• *{c.upper()}*: {data['accounts'][c]['quantity']} - `{data['accounts'][c]['price']} INR`"
                         for c in countries])

    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def show_account_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    country = query.data.split("_")[1]

    if not is_owner(user_id):
        is_member = await check_user_membership(context, user_id)
        if not is_member:
            await show_force_join_message(update, context)
            return

    if country not in data["accounts"]:
        await query.edit_message_text("❌ *Country not found!*")
        return

    account_info = data["accounts"][country]
    price = account_info["price"]
    balance = get_user_data(user_id)["balance"]

    text = f"""
📱 *{country.upper()} Virtual Account*

💰 *Price:* `{price} INR`
📊 *Available:* `{account_info['quantity']}`
💳 *Your Balance:* `{balance} INR`
    """

    keyboard = [
        [InlineKeyboardButton("💳 BUY NUMBER", callback_data=f"buy_number_{country}")],
        [InlineKeyboardButton("🎟 DISCOUNT CODE", callback_data="discount")],
        [InlineKeyboardButton("🔙 Back", callback_data="virtual_accounts")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def process_buy_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask quantity"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    country = query.data.split("_")[2]

    if not is_owner(user_id):
        is_member = await check_user_membership(context, user_id)
        if not is_member:
            await show_force_join_message(update, context)
            return ConversationHandler.END

    account_info = data["accounts"][country]
    price = account_info["price"]
    balance = get_user_data(user_id)["balance"]
    available = account_info["quantity"]

    text = f"""
🛒 *Purchase {country.upper()}*

📊 *Available:* `{available}`
💰 *Price:* `{price} INR each`
💳 *Your Balance:* `{balance} INR`

📝 *How many accounts? (1-{available}):*
    """

    await query.edit_message_text(text, parse_mode='Markdown')
    set_user_state(user_id, WAITING_FOR_QUANTITY, {"country": country, "price": price, "available": available})
    return WAITING_FOR_QUANTITY

async def handle_quantity_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle quantity"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    try:
        quantity = int(text)
        state = get_user_state(user_id)
        country = state["data"]["country"]
        price = state["data"]["price"]
        available = state["data"]["available"]

        if quantity <= 0:
            await update.message.reply_text("❌ *Minimum 1 account!*", parse_mode='Markdown')
            return WAITING_FOR_QUANTITY

        if quantity > available:
            await update.message.reply_text(f"❌ *Only {available} available!*", parse_mode='Markdown')
            return WAITING_FOR_QUANTITY

        total_price = price * quantity
        balance = get_user_data(user_id)["balance"]
        username = data["users"][str(user_id)]["username"]

        if balance < total_price:
            await log_insufficient_balance(context, user_id, username, total_price, balance)

            text = f"""
❌ *Insufficient Balance!*

💰 *Required:* `{total_price} INR`
💳 *Your Balance:* `{balance} INR`

➕ *Add funds first!*
            """
            keyboard = [[InlineKeyboardButton("➕ Add Funds", callback_data="add_funds")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            clear_user_state(user_id)
            return ConversationHandler.END

        confirmation_text = f"""
🛒 *Confirm Purchase*

📱 *Country:* `{country.upper()}`
📊 *Quantity:* `{quantity}`
💰 *Total:* `{total_price} INR`
💳 *Remaining:* `{balance - total_price} INR`

⚡ *Ready to buy?*
        """

        keyboard = [
            [InlineKeyboardButton("✅ CONFIRM", callback_data=f"confirm_buy_{country}_{quantity}")],
            [InlineKeyboardButton("❌ CANCEL", callback_data=f"country_{country}")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(confirmation_text, reply_markup=reply_markup, parse_mode='Markdown')
        clear_user_state(user_id)
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ *Invalid! Enter numbers only.*", parse_mode='Markdown')
        return WAITING_FOR_QUANTITY

async def confirm_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process purchase"""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    parts = query.data.split("_")
    country = parts[2]
    quantity = int(parts[3])
    username = data["users"][str(user_id)]["username"]

    account_info = data["accounts"][country]
    price = account_info["price"] * quantity
    balance = get_user_data(user_id)["balance"]

    if balance < price:
        await query.answer("❌ Insufficient balance!", show_alert=True)
        return

    if account_info["quantity"] < quantity:
        await query.answer("❌ Not enough accounts!", show_alert=True)
        return

    sessions = account_info.get("sessions", [])
    if len(sessions) < quantity:
        await query.answer("❌ Not enough sessions!", show_alert=True)
        return

    purchased_sessions = sessions[:quantity]
    remaining_sessions = sessions[quantity:]

    data["users"][str(user_id)]["balance"] -= price
    purchase_record = {
        "country": country,
        "quantity": quantity,
        "price": price,
        "sessions": purchased_sessions,
        "timestamp": datetime.now().isoformat(),
        "status": "completed"
    }
    data["users"][str(user_id)]["purchases"].append(purchase_record)

    account_info["quantity"] -= quantity
    account_info["sessions"] = remaining_sessions

    save_data(data)

    # Fetch phone numbers for logging
    async def fetch_phone_for_log(session_data):
        session_string = session_data.get("session")
        if session_string:
            try:
                client = await create_client(session_string, f"{user_id}_log")
                if client:
                    phone = await get_phone_number(client)
                    await client.stop()
                    return phone
            except:
                pass
        return "Error fetching"

    phone_numbers = []
    for session_data in purchased_sessions:
        phone = await fetch_phone_for_log(session_data)
        phone_numbers.append(phone)

    await log_number_purchase(context, user_id, username, country, quantity, price, phone_numbers)

    text = f"""
🎉 *Purchase Successful!*

✅ *{quantity} {country.upper()} account(s)!*
💰 *Deducted:* `{price} INR`
💳 *Balance:* `{data["users"][str(user_id)]["balance"]} INR`

⚡ *Next Steps:*
1️⃣ Click "GET NUMBER"
2️⃣ Start Telegram login
3️⃣ Click "GET OTP"
4️⃣ Complete login
    """

    keyboard = [
        [InlineKeyboardButton("📱 GET NUMBER", callback_data=f"get_number_{user_id}_{len(data['users'][str(user_id)]['purchases'])-1}")],
        [InlineKeyboardButton("🛒 Buy More", callback_data="virtual_accounts")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def get_number_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch phone numbers"""
    query = update.callback_query
    await query.answer("📱 Fetching...")

    parts = query.data.split("_")
    user_id = int(parts[2])
    purchase_index = int(parts[3])

    user_purchases = data["users"][str(user_id)]["purchases"]
    if purchase_index >= len(user_purchases):
        await query.answer("❌ Purchase not found!", show_alert=True)
        return

    purchase = user_purchases[purchase_index]
    sessions = purchase.get("sessions", [])

    if not sessions:
        await query.answer("❌ No sessions!", show_alert=True)
        return

    async def fetch_phone(i, session_data):
        session_string = session_data.get("session")
        if session_string:
            try:
                client = await create_client(session_string, f"{user_id}_{i}")
                if client:
                    phone = await get_phone_number(client)
                    await client.stop()
                    return phone
            except:
                pass
        return "Error"

    tasks = [fetch_phone(i, s) for i, s in enumerate(sessions)]
    phone_numbers = await asyncio.gather(*tasks)

    # store phones inside purchase sessions for later OTP display
    for idx, ph in enumerate(phone_numbers):
        try:
            purchase["sessions"][idx]["phone_number"] = ph
        except:
            pass
    save_data(data)

    text = f"""
📱 *Phone Numbers Retrieved!*

*Country:* `{purchase['country'].upper()}`
*Quantity:* `{purchase['quantity']}`

"""

    for i, phone in enumerate(phone_numbers, 1):
        text += f"\n*Account {i}:*\n📞 `{phone}`\n"

    text += f"""

⚡ *Next Steps:*
1️⃣ Use numbers to login on Telegram
2️⃣ Click "GET OTP" for verification
3️⃣ Complete login
    """

    keyboard = [
        [InlineKeyboardButton("🔍 GET OTP", callback_data=f"get_otp_{user_id}_{purchase_index}")],
        [InlineKeyboardButton("✅ LOGIN COMPLETE", callback_data=f"login_complete_{user_id}")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def get_otp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch OTP - UPDATED FORMAT + 2FA SHOW"""
    query = update.callback_query
    await query.answer("🔍 Searching OTP...")

    parts = query.data.split("_")
    user_id = int(parts[2])
    purchase_index = int(parts[3])
    username = data["users"][str(user_id)]["username"]

    user_purchases = data["users"][str(user_id)]["purchases"]
    if purchase_index >= len(user_purchases):
        await query.answer("❌ Purchase not found!", show_alert=True)
        return

    purchase = user_purchases[purchase_index]
    sessions = purchase.get("sessions", [])
    country = purchase.get("country", "Unknown")

    if not sessions:
        await query.answer("❌ No sessions!", show_alert=True)
        return

    loading_text = f"""
🔍 *Fetching OTP...*

*Country:* `{purchase['country'].upper()}`
*Quantity:* `{purchase['quantity']}`

⏳ *Checking Telegram (777000)...*
💡 *Make sure you started login!*
    """
    await query.edit_message_text(loading_text, parse_mode='Markdown')

    async def fetch_otp(i, session_data):
        session_string = session_data.get("session")
        phone = session_data.get("phone_number", "N/A")
        twofa = session_data.get("twofa")  # may be None
        if session_string:
            client = None
            try:
                client = await create_client(session_string, f"{user_id}_{i}_otp")
                if client:
                    # ensure phone exists if not stored
                    if phone in ["N/A", None, "Error"]:
                        try:
                            phone = await get_phone_number(client)
                        except:
                            phone = session_data.get("phone_number", "N/A")

                    otp = await get_otp_from_telegram(client)
                    await client.stop()
                    if otp:
                        # NEW FORMAT: otp fetch - (otp) (number)
                        msg = f"✅ otp fetch - `{otp}` `{phone}`"
                        if twofa:
                            msg += f"\n🔐 2FA: `{twofa}`"
                        return {"status": "success", "otp": otp, "phone": phone, "twofa": twofa, "message": msg}

                    msg = "⏳ OTP not found yet"
                    return {"status": "not_found", "otp": None, "phone": phone, "twofa": twofa, "message": msg}
            except Exception as e:
                if client:
                    try:
                        await client.stop()
                    except:
                        pass
                return {"status": "error", "otp": None, "phone": phone, "twofa": twofa, "message": f"❌ Error: {str(e)[:30]}"}
        return {"status": "error", "otp": None, "phone": phone, "twofa": twofa, "message": "❌ No session"}

    tasks = [fetch_otp(i, s) for i, s in enumerate(sessions)]
    otp_results = await asyncio.gather(*tasks)

    text = f"""
🔑 *OTP Retrieval Results*

*Country:* `{purchase['country'].upper()}`
*Quantity:* `{purchase['quantity']}`

"""

    success_count = 0
    for i, result in enumerate(otp_results, 1):
        text += f"\n*Account {i}:*\n{result['message']}\n"
        if result['status'] == 'success':
            success_count += 1

    await log_otp_fetched(context, user_id, username, country, success_count, len(sessions))

    if success_count > 0:
        text += f"\n✅ *Found {success_count} OTP(s)!*\n⏰ *Use quickly (expires soon)*"
    else:
        text += f"\n⚠️ *No OTP found yet!*\n💡 *Start login first, then try again*"

    keyboard = [
        [InlineKeyboardButton("🔄 TRY AGAIN", callback_data=f"get_otp_{user_id}_{purchase_index}")],
        [InlineKeyboardButton("✅ LOGIN COMPLETE", callback_data=f"login_complete_{user_id}")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# Balance Functions
async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split("_")[2])

    if not is_owner(user_id):
        is_member = await check_user_membership(context, user_id)
        if not is_member:
            await show_force_join_message(update, context)
            return

    balance = get_user_data(user_id)["balance"]

    text = f"""
💳 *My Balance*

💰 *Current Balance:* `{balance} INR`

📊 *Recent Transactions:*
"""

    purchases = data["users"][str(user_id)]["purchases"][-3:]
    if not purchases:
        text += "\n• No transactions"
    else:
        for p in purchases:
            text += f"\n• *{p['country'].upper()}* - {p['quantity']}x - `{p['price']} INR`"

    keyboard = [
        [InlineKeyboardButton("➕ Add Funds", callback_data="add_funds")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# Add Funds Flow
async def show_add_funds_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if not is_owner(user_id):
        is_member = await check_user_membership(context, user_id)
        if not is_member:
            await show_force_join_message(update, context)
            return

    clear_user_state(user_id)

    text = """
➕ *Add Funds*

💳 *Choose method:*

1️⃣ *Buy Funds (UPI)* - Instant
2️⃣ *Coupon Code* - Redeem

💡 *Minimum: 10 INR*
    """

    keyboard = [
        [InlineKeyboardButton("💸 Buy Funds (UPI)", callback_data="buy_fund")],
        [InlineKeyboardButton("🎟 Coupon Code", callback_data="coupon_code")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def ask_fund_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    text = """
💰 *Enter Amount*

💡 *Minimum 10 INR*

Example: `50` or `100`

📝 *Reply with amount:*
    """

    await query.edit_message_text(text, parse_mode='Markdown')
    set_user_state(user_id, WAITING_FOR_AMOUNT)
    return WAITING_FOR_AMOUNT

async def handle_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle amount input"""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    try:
        amount = int(text)
        if amount < 10:
            await update.message.reply_text("❌ *Minimum 10 INR!*", parse_mode='Markdown')
            return WAITING_FOR_AMOUNT

        data["pending_payments"][str(user_id)] = {
            "amount": amount,
            "timestamp": datetime.now().isoformat(),
            "status": "waiting_screenshot"
        }
        save_data(data)

        qr_image = generate_upi_qr(amount)

        payment_text = f"""
💸 *Payment Details*

💰 *Amount:* `{amount} INR`
👤 *UPI ID:* `{UPI_ID}`

📱 *PAY VIA QR CODE:*
⬇️ *Scan QR below with any UPI app*

OR

💳 *MANUAL PAYMENT:*
1. Open any UPI app (GPay/PhonePe/Paytm)
2. Send `{amount} INR` to: `{UPI_ID}`
3. Take screenshot of payment
4. Send screenshot here

⏰ *Processing: 5-10 min*
        """

        if qr_image:
            await update.message.reply_photo(
                photo=qr_image,
                caption=payment_text,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(payment_text, parse_mode='Markdown')

        set_user_state(user_id, WAITING_FOR_SCREENSHOT, {"amount": amount})
        return WAITING_FOR_SCREENSHOT

    except ValueError:
        await update.message.reply_text("❌ *Invalid! Numbers only.*", parse_mode='Markdown')
        return WAITING_FOR_AMOUNT

async def ask_coupon_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    text = """
🎟 *Enter Coupon Code*

Example: `WELCOME10`

📝 *Reply with code:*
    """

    await query.edit_message_text(text, parse_mode='Markdown')
    set_user_state(user_id, WAITING_FOR_COUPON)
    return WAITING_FOR_COUPON

async def handle_coupon_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle coupon input"""
    user_id = update.effective_user.id
    coupon_code = update.message.text.strip().upper()
    username = data["users"][str(user_id)]["username"]

    if coupon_code not in data["coupons"]:
        await update.message.reply_text("❌ *Invalid coupon!*", parse_mode='Markdown')
        clear_user_state(user_id)
        return ConversationHandler.END

    if has_used_coupon(user_id, coupon_code):
        await update.message.reply_text(
            "❌ *You already used this coupon!*\n\n"
            "💡 *Each coupon can only be used once per user.*",
            parse_mode='Markdown'
        )
        clear_user_state(user_id)
        return ConversationHandler.END

    coupon = data["coupons"][coupon_code]

    get_user_data(user_id)["balance"] += coupon["amount"]
    mark_coupon_used(user_id, coupon_code)
    coupon["uses_left"] -= 1

    if coupon["uses_left"] <= 0:
        del data["coupons"][coupon_code]

    save_data(data)

    await log_coupon_redeemed(context, user_id, username, coupon_code, coupon["amount"])

    text = f"""
✅ *Coupon Redeemed!*

🎟 *Code:* `{coupon_code}`
💰 *Added:* `{coupon['amount']} INR`
💳 *Balance:* `{get_user_data(user_id)['balance']} INR`

⚠️ *This coupon is now used and cannot be redeemed again by you!*
    """

    keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

    clear_user_state(user_id)
    return ConversationHandler.END

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle payment screenshot"""
    user_id = update.effective_user.id
    state = get_user_state(user_id)
    username = data["users"][str(user_id)]["username"]

    if state["state"] != WAITING_FOR_SCREENSHOT:
        await update.message.reply_text("❌ *No pending payment.*", parse_mode='Markdown')
        return ConversationHandler.END

    photo = update.message.photo[-1]
    amount = state["data"].get("amount", 0)

    await log_payment_submitted(context, user_id, username, amount)

    caption = f"""
🔔 *New Payment!*

👤 *User:* {username}
🆔 *ID:* `{user_id}`
💰 *Amount:* `{amount} INR`
⏰ *Time:* {datetime.now().strftime('%H:%M %d/%m')}

🔍 *Please verify!*
    """

    keyboard = [
        [InlineKeyboardButton("✅ APPROVE", callback_data=f"approve_fund_{user_id}_{amount}")],
        [InlineKeyboardButton("❌ REJECT", callback_data=f"reject_fund_{user_id}")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await context.bot.forward_message(
            chat_id=OWNER_ID,
            from_chat_id=update.effective_chat.id,
            message_id=update.message.message_id
        )

        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=caption,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"[SCREENSHOT ERROR] {e}")
        await update.message.reply_text(
            "❌ *Error occurred! Try again by /start*\n\n"
            "💡 *Or contact:* @lTZ_ME_ADITYA_02",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    balance_keyboard = [[InlineKeyboardButton("💳 Balance", callback_data=f"my_balance_{user_id}")]]
    balance_reply_markup = InlineKeyboardMarkup(balance_keyboard)

    await update.message.reply_text(
        "✅ *Screenshot received!*\n\n"
        "🔄 *Owner will verify in 5-10 min*\n"
        "💳 *Check balance anytime*",
        reply_markup=balance_reply_markup,
        parse_mode='Markdown'
    )

    data["pending_payments"][str(user_id)] = {
        "amount": amount,
        "screenshot": photo.file_id,
        "timestamp": datetime.now().isoformat(),
        "status": "submitted"
    }
    save_data(data)
    clear_user_state(user_id)
    return ConversationHandler.END

# Owner Fund Approval
async def approve_fund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("✅ Approved!")
    parts = query.data.split("_")
    user_id = int(parts[2])
    amount = int(parts[3])
    username = data["users"][str(user_id)]["username"]

    get_user_data(user_id)["balance"] += amount
    save_data(data)

    if str(user_id) in data["pending_payments"]:
        data["pending_payments"][str(user_id)]["status"] = "approved"
        save_data(data)

    await log_payment_approved(context, user_id, username, amount)

    main_menu_keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
    main_menu_reply_markup = InlineKeyboardMarkup(main_menu_keyboard)

    await context.bot.send_message(
        user_id,
        f"🎉 *Funds Added!*\n\n"
        f"💰 *Amount:* `{amount} INR`\n"
        f"💳 *Balance:* `{get_user_data(user_id)['balance']} INR`",
        parse_mode='Markdown',
        reply_markup=main_menu_reply_markup
    )

    await query.edit_message_text(f"✅ *Approved {amount} INR for user {user_id}!*", parse_mode='Markdown')

async def reject_fund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("❌ Rejected!")
    user_id = int(query.data.split("_")[2])
    username = data["users"].get(str(user_id), {}).get("username", f"User_{user_id}")

    amount = data["pending_payments"].get(str(user_id), {}).get("amount", 0)

    await log_payment_rejected(context, user_id, username, amount)

    await context.bot.send_message(
        user_id,
        "❌ *Payment Rejected!*\n\n"
        "💡 *Try again with correct amount*\n"
        "📞 *Contact:* @lTZ_ME_ADITYA_02",
        parse_mode='Markdown'
    )

    if str(user_id) in data["pending_payments"]:
        data["pending_payments"][str(user_id)]["status"] = "rejected"
        save_data(data)

    await query.edit_message_text(f"❌ *Rejected user {user_id}!*", parse_mode='Markdown')

# Owner Panel
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        if update.message:
            await update.message.reply_text("❌ *Unauthorized!*", parse_mode='Markdown')
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("➕ Add Number", callback_data="owner_addnumber")],
        [InlineKeyboardButton("🗑 Delete Country", callback_data="owner_delete")],
        [InlineKeyboardButton("🎟 Create Discount", callback_data="owner_discount")],
        [InlineKeyboardButton("💰 Create Coupon", callback_data="owner_coupon")],
        [InlineKeyboardButton("📣 Broadcast", callback_data="owner_broadcast")],
        [InlineKeyboardButton("📊 View Payments", callback_data="owner_payments")],
        [InlineKeyboardButton("👥 User Stats", callback_data="owner_stats")],
        [InlineKeyboardButton("📸 Set Bot Photo", callback_data="owner_setdp")],
        [InlineKeyboardButton("🏠 Close", callback_data="main_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    text = """
🔧 *Owner Panel*

👑 *Welcome Admin!*

Choose action:
    """

    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def owner_add_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    text = """
➕ *Add Numbers*

📝 *Enter country name:*

Examples: `USA`, `INDIA`, `KENYA`
    """

    await query.edit_message_text(text, parse_mode='Markdown')
    set_user_state(user_id, WAITING_FOR_COUNTRY)
    return WAITING_FOR_COUNTRY

async def handle_country_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return ConversationHandler.END

    country = update.message.text.strip().upper()

    if country in data["accounts"]:
        existing_info = data["accounts"][country]
        text = f"""
⚠️ *'{country}' exists!*

📊 *Current:*
• Price: `{existing_info['price']} INR`
• Available: `{existing_info['quantity']}`

💡 *Type:*
• `ADD` - Add more sessions
• `NEW` - Change price + add
• `CANCEL` - Cancel
        """
        await update.message.reply_text(text, parse_mode='Markdown')
        set_user_state(user_id, WAITING_FOR_ADD_MORE_SESSIONS, {"country": country, "price": existing_info['price']})
        return WAITING_FOR_ADD_MORE_SESSIONS

    set_user_state(user_id, WAITING_FOR_PRICE, {"country": country})

    text = f"""
💰 *Set Price for {country}*

💡 *Enter price in INR:*

Example: `60`
    """

    await update.message.reply_text(text, parse_mode='Markdown')
    return WAITING_FOR_PRICE

async def handle_add_more_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle add more choice"""
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return ConversationHandler.END

    choice = update.message.text.strip().upper()
    state = get_user_state(user_id)
    country = state["data"]["country"]
    old_price = state["data"]["price"]

    if choice == "CANCEL":
        await update.message.reply_text("❌ *Cancelled!*", parse_mode='Markdown')
        clear_user_state(user_id)
        return ConversationHandler.END

    elif choice == "ADD":
        text = f"""
🔗 *Add Sessions for {country}*

💰 *Price:* `{old_price} INR`

📝 *Send session string:*
        """
        await update.message.reply_text(text, parse_mode='Markdown')
        # NEW FLOW: after session ask 2FA then add
        set_user_state(user_id, WAITING_FOR_SESSION, {"country": country, "price": old_price, "mode": "add_more"})
        return WAITING_FOR_SESSION

    elif choice == "NEW":
        text = f"""
💰 *NEW Price for {country}*

💡 *Old:* `{old_price} INR`
📝 *Enter new price:*
        """
        await update.message.reply_text(text, parse_mode='Markdown')
        set_user_state(user_id, WAITING_FOR_PRICE, {"country": country, "mode": "new_price"})
        return WAITING_FOR_PRICE

    else:
        await update.message.reply_text("❌ *Type ADD, NEW, or CANCEL*", parse_mode='Markdown')
        return WAITING_FOR_ADD_MORE_SESSIONS

async def handle_price_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return ConversationHandler.END

    text = update.message.text.strip()

    try:
        price = int(text)
        state = get_user_state(user_id)
        country = state["data"]["country"]

        if country not in data["accounts"]:
            data["accounts"][country] = {
                "price": price,
                "quantity": 0,
                "sessions": []
            }
        else:
            data["accounts"][country]["price"] = price
        save_data(data)

        # NEW FLOW: session first, then 2FA question, then add
        set_user_state(user_id, WAITING_FOR_SESSION, {"country": country, "price": price})

        response_text = f"""
🔗 *Add Sessions for {country}*

💰 *Price:* `{price} INR`

📝 *Send session string:*
        """

        await update.message.reply_text(response_text, parse_mode='Markdown')
        return WAITING_FOR_SESSION

    except ValueError:
        await update.message.reply_text("❌ *Invalid! Numbers only.*", parse_mode='Markdown')
        return WAITING_FOR_PRICE

# ---------- NEW: session input does NOT add immediately ----------
async def handle_session_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return ConversationHandler.END

    text = update.message.text.strip()
    state = get_user_state(user_id)
    country = state["data"]["country"]
    price = state["data"]["price"]

    # allow canceling session-add flow completely
    if text == "/skip" and state["state"] == WAITING_FOR_SESSION:
        clear_user_state(user_id)
        await update.message.reply_text(
            f"✅ *Completed for {country}!*\n\n" +
            "\n".join([f"• *{c}*: {info['quantity']} - {info['price']} INR"
                      for c, info in data["accounts"].items()]),
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    if len(text) < 50:
        await update.message.reply_text("❌ *Session too short!*", parse_mode='Markdown')
        return WAITING_FOR_SESSION

    # store session temporarily, ask for 2FA
    set_user_state(user_id, WAITING_FOR_2FA, {"country": country, "price": price, "pending_session": text})
    await update.message.reply_text(
        "🔐 *2FA hai?*\n\n"
        "✅ Agar 2FA hai to password bhejo.\n"
        "❌ Agar nahi hai to `/skip` likho.",
        parse_mode='Markdown'
    )
    return WAITING_FOR_2FA

async def handle_2fa_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """If owner sends 2FA or /skip, then add session finally"""
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return ConversationHandler.END

    state = get_user_state(user_id)
    if state["state"] != WAITING_FOR_2FA:
        return ConversationHandler.END

    country = state["data"]["country"]
    price = state["data"]["price"]
    session_string = state["data"]["pending_session"]
    msg = update.message.text.strip()

    twofa = None
    if msg != "/skip":
        twofa = msg

    # Fetch phone number from session before saving
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

    response_text = f"""
✅ *Added!*

📱 *Country:* `{country}`
📞 *Phone:* `{phone_number}`
💰 *Price:* `{price} INR`
📊 *Total:* `{data["accounts"][country]["quantity"]}`

💡 *Add another session string OR finish with `/skip`:*
    """
    await update.message.reply_text(response_text, parse_mode='Markdown')

    # go back to WAITING_FOR_SESSION for next session
    set_user_state(user_id, WAITING_FOR_SESSION, {"country": country, "price": price})
    return WAITING_FOR_SESSION

# Owner Discount/Coupon
async def create_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if not is_owner(user_id):
        return ConversationHandler.END

    text = """
🎟 *Create Discount*

💰 *Enter discount in INR:*

Example: `10` for 10 INR off

⚠️ *Each user can use this discount only ONCE*
    """

    await query.edit_message_text(text, parse_mode='Markdown')
    set_user_state(user_id, WAITING_FOR_DISCOUNT_AMOUNT)
    return WAITING_FOR_DISCOUNT_AMOUNT

async def handle_discount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return ConversationHandler.END

    text = update.message.text.strip()

    try:
        discount = int(text)
        import secrets
        code = f"DISCOUNT_{secrets.token_hex(4).upper()}"

        data["discount_codes"][code] = {
            "discount": discount,
            "uses_left": 999999,
            "created": datetime.now().isoformat()
        }
        save_data(data)

        await log_discount_created(context, code, discount)

        response_text = f"""
✅ *Discount Created!*

🎟 *Code:* `{code}`
💰 *Discount:* `{discount} INR`
📊 *Usage:* One-time per user

*Copy:* `{code}`
        """

        keyboard = [[InlineKeyboardButton("🏠 Panel", callback_data="owner_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(response_text, reply_markup=reply_markup, parse_mode='Markdown')
        clear_user_state(user_id)
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ *Numbers only!*", parse_mode='Markdown')
        return WAITING_FOR_DISCOUNT_AMOUNT

async def create_coupon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if not is_owner(user_id):
        return ConversationHandler.END

    text = """
💰 *Create Coupon*

💵 *Enter amount in INR:*

Example: `50` for 50 INR

⚠️ *Each user can use this coupon only ONCE*
    """

    await query.edit_message_text(text, parse_mode='Markdown')
    set_user_state(user_id, WAITING_FOR_COUPON_AMOUNT)
    return WAITING_FOR_COUPON_AMOUNT

async def handle_coupon_input_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return ConversationHandler.END

    text = update.message.text.strip()

    try:
        amount = int(text)
        import secrets
        code = f"COUPON_{secrets.token_hex(4).upper()}"

        data["coupons"][code] = {
            "amount": amount,
            "uses_left": 999999,
            "created": datetime.now().isoformat()
        }
        save_data(data)

        await log_coupon_created(context, code, amount)

        response_text = f"""
✅ *Coupon Created!*

🎟 *Code:* `{code}`
💰 *Amount:* `{amount} INR`
📊 *Usage:* One-time per user

*Copy:* `{code}`
        """

        keyboard = [[InlineKeyboardButton("🏠 Panel", callback_data="owner_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(response_text, reply_markup=reply_markup, parse_mode='Markdown')
        clear_user_state(user_id)
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ *Numbers only!*", parse_mode='Markdown')
        return WAITING_FOR_COUPON_AMOUNT

# Broadcast Feature
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if not is_owner(user_id):
        return ConversationHandler.END

    text = f"""
📣 *Broadcast Message*

👥 *Total Users:* `{len(data['users'])}`

📝 *Type your message:*

⚠️ *This will send to ALL users!*
    """

    await query.edit_message_text(text, parse_mode='Markdown')
    set_user_state(user_id, WAITING_FOR_BROADCAST_MESSAGE)
    return WAITING_FOR_BROADCAST_MESSAGE

async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return ConversationHandler.END

    broadcast_message = update.message.text
    total_users = len(data['users'])

    confirmation_text = f"""
📣 *Confirm Broadcast*

👥 *Recipients:* `{total_users} users`

📝 *Message Preview:*
{broadcast_message[:500]}{"..." if len(broadcast_message) > 500 else ""}

⚠️ *Send to all users?*
    """

    keyboard = [
        [InlineKeyboardButton("✅ SEND", callback_data=f"broadcast_confirm")],
        [InlineKeyboardButton("❌ CANCEL", callback_data="owner_panel")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(confirmation_text, reply_markup=reply_markup, parse_mode='Markdown')

    set_user_state(user_id, WAITING_FOR_BROADCAST_MESSAGE, {"message": broadcast_message})
    return ConversationHandler.END

async def broadcast_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("📤 Sending...")
    user_id = update.effective_user.id

    if not is_owner(user_id):
        return

    state = get_user_state(user_id)
    broadcast_message = state["data"].get("message", "")

    if not broadcast_message:
        await query.edit_message_text("❌ *No message found!*", parse_mode='Markdown')
        return

    total_users = len(data['users'])
    success_count = 0
    failed_count = 0

    progress_text = f"""
📤 *Broadcasting...*

👥 *Total:* `{total_users}`
✅ *Sent:* `0`
❌ *Failed:* `0`

⏳ *Please wait...*
    """
    await query.edit_message_text(progress_text, parse_mode='Markdown')

    for user_id_str in data['users'].keys():
        try:
            target_user_id = int(user_id_str)
            await context.bot.send_message(
                chat_id=target_user_id,
                text=f"📣 *Broadcast Message*\n\n{broadcast_message}",
                parse_mode='Markdown'
            )
            success_count += 1

            if success_count % 10 == 0:
                progress_text = f"""
📤 *Broadcasting...*

👥 *Total:* `{total_users}`
✅ *Sent:* `{success_count}`
❌ *Failed:* `{failed_count}`

⏳ *In progress...*
                """
                try:
                    await query.edit_message_text(progress_text, parse_mode='Markdown')
                except:
                    pass

            await asyncio.sleep(0.05)

        except Exception as e:
            failed_count += 1
            logger.error(f"[BROADCAST ERROR] User {user_id_str}: {e}")

    await log_broadcast_sent(context, total_users, success_count, failed_count)

    final_text = f"""
✅ *Broadcast Complete!*

👥 *Total:* `{total_users}`
✅ *Sent:* `{success_count}`
❌ *Failed:* `{failed_count}`

📊 *Success Rate:* `{(success_count/total_users*100):.1f}%`
    """

    keyboard = [[InlineKeyboardButton("🏠 Panel", callback_data="owner_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(final_text, reply_markup=reply_markup, parse_mode='Markdown')
    clear_user_state(user_id)

# Owner Delete Country
async def owner_delete_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if not is_owner(user_id):
        return

    countries = [c for c in data["accounts"] if data["accounts"][c]["quantity"] >= 0]

    if not countries:
        text = "📭 *No countries to delete!*"
        keyboard = [[InlineKeyboardButton("🏠 Panel", callback_data="owner_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        return

    keyboard = []
    for country in countries:
        keyboard.append([InlineKeyboardButton(f"🗑 {country.upper()}", callback_data=f"delete_confirm_{country}")])

    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="owner_panel")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    text = """
🗑 *Delete Country*

⚠️ *This removes all accounts!*

Choose country:
    """

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def confirm_delete_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    country = query.data.split("_")[2]

    if not is_owner(user_id):
        return

    if country in data["accounts"]:
        quantity = data["accounts"][country]["quantity"]
        price = data["accounts"][country]["price"]

        await log_country_deleted(context, country, quantity, price)

        del data["accounts"][country]
        save_data(data)

        text = f"""
✅ *Deleted!*

📱 *Country:* `{country.upper()}`
📊 *Removed:* `{quantity}`
💰 *Price:* `{price} INR`
        """
    else:
        text = f"❌ *'{country}' not found!*"

    keyboard = [[InlineKeyboardButton("🏠 Panel", callback_data="owner_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# Owner View Payments
async def owner_view_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if not is_owner(user_id):
        return

    pending_payments = {uid: info for uid, info in data["pending_payments"].items()
                        if info["status"] == "submitted"}

    if not pending_payments:
        text = "📭 *No pending payments!*"
        keyboard = [[InlineKeyboardButton("🏠 Panel", callback_data="owner_panel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        return

    text = "💳 *Pending Payments*\n\n"

    keyboard = []
    for payment_user_id, info in list(pending_payments.items())[:5]:
        username = data["users"].get(str(payment_user_id), {}).get("username", f"User_{payment_user_id}")
        amount = info["amount"]
        time = datetime.fromisoformat(info["timestamp"]).strftime('%H:%M %d/%m')

        text += f"👤 *{username}*\n💰 `{amount} INR` - `{time}`\n\n"

        keyboard.append([InlineKeyboardButton(
            f"🔍 {username} - {amount} INR",
            callback_data=f"review_payment_{payment_user_id}"
        )])

    keyboard.append([InlineKeyboardButton("🏠 Panel", callback_data="owner_panel")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# Owner Stats
async def owner_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if not is_owner(user_id):
        return

    total_users = len(data["users"])
    total_balance = sum(user["balance"] for user in data["users"].values())
    total_revenue = sum(purchase["price"] for user in data["users"].values()
                        for purchase in user["purchases"] if purchase.get("status") == "completed")

    available_accounts = sum(info["quantity"] for info in data["accounts"].values())

    text = f"""
📊 *Bot Statistics*

👥 *Total Users:* `{total_users}`
💰 *User Balance:* `{total_balance} INR`
💵 *Revenue:* `{total_revenue} INR`

📱 *Available:* `{available_accounts}`

🌍 *By Country:*
"""

    for country, info in data["accounts"].items():
        if info["quantity"] > 0:
            text += f"\n• *{country}*: `{info['quantity']}` - `{info['price']} INR`"

    text += f"\n\n⏰ `{datetime.now().strftime('%H:%M %d/%m/%Y')}`"

    keyboard = [[InlineKeyboardButton("🏠 Panel", callback_data="owner_panel")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# Set Bot Photo
async def set_bot_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        if update.message:
            await update.message.reply_text("❌ *Unauthorized!*", parse_mode='Markdown')
        return

    if update.message:
        await update.message.reply_text(
            "📸 *Send bot picture:*\n\n"
            "💡 *JPG/PNG, 512x512*",
            parse_mode='Markdown'
        )
    elif update.callback_query:
        await update.callback_query.edit_message_text(
            "📸 *Send bot picture:*\n\n"
            "💡 *JPG/PNG, 512x512*",
            parse_mode='Markdown'
        )

    set_user_state(user_id, WAITING_FOR_BOT_PHOTO)
    return WAITING_FOR_BOT_PHOTO

async def handle_photo_owner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_user_state(user_id)

    if state["state"] != WAITING_FOR_BOT_PHOTO or not is_owner(user_id):
        return ConversationHandler.END

    photo = update.message.photo[-1]
    data["bot_photo"] = photo.file_id
    save_data(data)

    panel_keyboard = [[InlineKeyboardButton("🏠 Panel", callback_data="owner_panel")]]
    panel_reply_markup = InlineKeyboardMarkup(panel_keyboard)

    await update.message.reply_text(
        "✅ *Bot photo updated!*\n\n"
        "📸 *Restart bot to see*",
        reply_markup=panel_reply_markup,
        parse_mode='Markdown'
    )

    clear_user_state(user_id)
    return ConversationHandler.END

# Discount Application
async def apply_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    text = """
🎟 *Apply Discount*

💡 *Enter code:*

Example: `DISCOUNT1234`
    """

    await query.edit_message_text(text, parse_mode='Markdown')
    set_user_state(user_id, WAITING_FOR_DISCOUNT_CODE)
    return WAITING_FOR_DISCOUNT_CODE

async def handle_discount_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle discount code"""
    user_id = update.effective_user.id
    state = get_user_state(user_id)
    username = data["users"][str(user_id)]["username"]

    if state["state"] != WAITING_FOR_DISCOUNT_CODE:
        return ConversationHandler.END

    code = update.message.text.strip().upper()

    if code not in data["discount_codes"]:
        await update.message.reply_text("❌ *Invalid code!*", parse_mode='Markdown')
        clear_user_state(user_id)
        return ConversationHandler.END

    if has_used_discount(user_id, code):
        await update.message.reply_text(
            "❌ *You already used this discount code!*\n\n"
            "💡 *Each discount can only be used once per user.*",
            parse_mode='Markdown'
        )
        clear_user_state(user_id)
        return ConversationHandler.END

    discount_info = data["discount_codes"][code]
    discount_amount = discount_info["discount"]

    mark_discount_used(user_id, code)

    user_state = get_user_state(user_id)
    if "discount" not in user_state["data"]:
        user_state["data"]["discount"] = 0
    user_state["data"]["discount"] += discount_amount
    set_user_state(user_id, user_state["state"], user_state["data"])

    await log_discount_applied(context, user_id, username, code, discount_amount)

    text = f"""
✅ *Discount Applied!*

🎟 *Code:* `{code}`
💰 *Discount:* `{discount_amount} INR`
💎 *Total Discount:* `{user_state["data"]["discount"]} INR`

⚠️ *This code is now used and cannot be applied again by you!*
    """

    keyboard = [[InlineKeyboardButton("🛒 Shop", callback_data="virtual_accounts")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

    clear_user_state(user_id)
    return ConversationHandler.END

# Login Complete
async def login_complete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("✅ Verified!")

    text = """
🎉 *Login Complete!*

✅ *Account activated!*
✅ *Ready to use!*

💡 *Keep sessions secure*

⭐ *Thank you!*
    """

    keyboard = [
        [InlineKeyboardButton("🛒 Buy More", callback_data="virtual_accounts")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# No Accounts
async def no_accounts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    text = """
📭 *No Accounts Available*

😔 *Out of stock!*

⏰ *Check back in 30 min*
    """

    keyboard = [
        [InlineKeyboardButton("➕ Add Funds", callback_data="add_funds")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

# Generic Button Handler
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    data_str = query.data

    try:
        if data_str == "verify_join":
            await verify_join_handler(update, context)
            return

        if not is_owner(user_id):
            is_member = await check_user_membership(context, user_id)
            if not is_member:
                await query.answer("⚠️ Join channel & group first!", show_alert=True)
                await show_force_join_message(update, context)
                return

        if data_str == "main_menu":
            await main_menu(update, context)
        elif data_str == "virtual_accounts":
            await show_countries(update, context)
        elif data_str.startswith("my_balance_"):
            await show_balance(update, context)
        elif data_str == "add_funds":
            await show_add_funds_options(update, context)
        elif data_str == "buy_fund":
            return await ask_fund_amount(update, context)
        elif data_str == "coupon_code":
            return await ask_coupon_code(update, context)
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
        elif data_str == "no_accounts":
            await no_accounts_handler(update, context)
        elif data_str == "owner_panel":
            await owner_panel(update, context)
        elif data_str == "owner_addnumber":
            return await owner_add_number(update, context)
        elif data_str == "owner_delete":
            await owner_delete_country(update, context)
        elif data_str.startswith("delete_confirm_"):
            await confirm_delete_country(update, context)
        elif data_str == "owner_discount":
            return await create_discount(update, context)
        elif data_str == "owner_coupon":
            return await create_coupon(update, context)
        elif data_str == "owner_broadcast":
            return await broadcast_start(update, context)
        elif data_str == "broadcast_confirm":
            await broadcast_confirm(update, context)
        elif data_str == "owner_payments":
            await owner_view_payments(update, context)
        elif data_str == "owner_stats":
            await owner_stats(update, context)
        elif data_str == "owner_setdp":
            return await set_bot_photo(update, context)
        elif data_str.startswith("approve_fund_"):
            await approve_fund(update, context)
        elif data_str.startswith("reject_fund_"):
            await reject_fund(update, context)
        elif data_str == "discount":
            return await apply_discount(update, context)
        else:
            await query.answer("⚠️ Unknown action!", show_alert=True)
    except Exception as e:
        logger.error(f"[BUTTON ERROR] {type(e).__name__}('{str(e)}')")
        await query.answer("❌ Error occurred! Try again by /start", show_alert=True)

# Error Handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ *Error occurred! Try again by /start*\n\n"
                "💡 *Or contact:* @lTZ_ME_ADITYA_02",
                parse_mode='Markdown'
            )
        except:
            pass

# Global fallback
async def global_text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state_info = get_user_state(user_id)
    current_state = state_info["state"]

    # OWNER: /add /deduct flow
    if current_state == WAITING_FOR_TARGET_USER_ID:
        return await owner_handle_target_user_id(update, context)
    if current_state == WAITING_FOR_TARGET_AMOUNT:
        return await owner_handle_target_amount(update, context)

    if current_state == WAITING_FOR_AMOUNT:
        return await handle_amount_input(update, context)
    elif current_state == WAITING_FOR_COUPON:
        return await handle_coupon_input(update, context)
    elif current_state == WAITING_FOR_COUNTRY:
        return await handle_country_input(update, context)
    elif current_state == WAITING_FOR_PRICE:
        return await handle_price_input(update, context)
    elif current_state == WAITING_FOR_SESSION:
        return await handle_session_input(update, context)
    elif current_state == WAITING_FOR_2FA:
        return await handle_2fa_input(update, context)
    elif current_state == WAITING_FOR_DISCOUNT_AMOUNT:
        return await handle_discount_input(update, context)
    elif current_state == WAITING_FOR_COUPON_AMOUNT:
        return await handle_coupon_input_owner(update, context)
    elif current_state == WAITING_FOR_DISCOUNT_CODE:
        return await handle_discount_code(update, context)
    elif current_state == WAITING_FOR_QUANTITY:
        return await handle_quantity_input(update, context)
    elif current_state == WAITING_FOR_ADD_MORE_SESSIONS:
        return await handle_add_more_choice(update, context)
    elif current_state == WAITING_FOR_BROADCAST_MESSAGE:
        return await handle_broadcast_message(update, context)
    else:
        await update.message.reply_text("Use /start to begin or /panel for owner", parse_mode='Markdown')
        clear_user_state(user_id)
        return ConversationHandler.END

# Main Conversation Handler
def get_conversation_handler():
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("panel", owner_panel),
            CommandHandler("add", owner_add_command),         # NEW
            CommandHandler("deduct", owner_deduct_command),   # NEW
            CallbackQueryHandler(button_handler)
        ],
        states={
            WAITING_FOR_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount_input)],
            WAITING_FOR_COUPON: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_coupon_input)],
            WAITING_FOR_SCREENSHOT: [MessageHandler(filters.PHOTO, handle_screenshot)],
            WAITING_FOR_COUNTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_country_input)],
            WAITING_FOR_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_price_input)],
            WAITING_FOR_SESSION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_session_input)],
            WAITING_FOR_2FA: [MessageHandler(filters.TEXT, handle_2fa_input)],  # accept /skip or password
            WAITING_FOR_DISCOUNT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_discount_input)],
            WAITING_FOR_COUPON_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_coupon_input_owner)],
            WAITING_FOR_DISCOUNT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_discount_code)],
            WAITING_FOR_BOT_PHOTO: [MessageHandler(filters.PHOTO, handle_photo_owner)],
            WAITING_FOR_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quantity_input)],
            WAITING_FOR_ADD_MORE_SESSIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_more_choice)],
            WAITING_FOR_BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast_message)],

            # /add /deduct
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

# Main function
def main():
    application = Application.builder().token(BOT_TOKEN).build()

    conv_handler = get_conversation_handler()
    application.add_handler(conv_handler)

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_text_fallback))
    application.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_photo_owner))

    application.add_error_handler(error_handler)

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🔥 VIRTUAL ACCOUNT BOT - UPDATED 🔥")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"\n👑 Owner: {OWNER_ID}")
    print(f"📊 Users: {len(data['users'])}")
    print(f"🌍 Countries: {len(data['accounts'])}")
    print(f"\n✅ NEW FEATURES:")
    print("   • ✅ /add (owner balance credit)")
    print("   • ✅ /deduct (owner balance debit)")
    print("   • ✅ Session add asks for 2FA before saving")
    print("   • ✅ Session log shows phone number + 2FA if exists")
    print("   • ✅ OTP display: otp fetch - (otp) (phone)")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🚀 Bot is LIVE! Press Ctrl+C to stop.")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True
    )

if __name__ == '__main__':
    main()
