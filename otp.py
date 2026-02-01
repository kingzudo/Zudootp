import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from io import BytesIO
from pyrogram import Client
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, 
    ConversationHandler, filters, ContextTypes
)
from telegram.error import BadRequest, TimedOut, NetworkError
import logging
import qrcode
import io

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
    WAITING_FOR_2FA,
    WAITING_FOR_LOGIN_STATUS,
    WAITING_FOR_DISCOUNT_CODE,
    WAITING_FOR_BOT_PHOTO,
    WAITING_FOR_QUANTITY,
    WAITING_FOR_ADD_MORE_SESSIONS,
    WAITING_FOR_BROADCAST_MESSAGE,
    WAITING_FOR_ADD_USER_ID,
    WAITING_FOR_ADD_AMOUNT,
    WAITING_FOR_DEDUCT_USER_ID,
    WAITING_FOR_DEDUCT_AMOUNT
) = range(19)

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

# ============ LOGGING SYSTEM ============
async def send_log_to_support(context: ContextTypes.DEFAULT_TYPE, log_message: str):
    """Send detailed logs to support group"""
    try:
        await context.bot.send_message(chat_id=SUPPORT_GROUP_ID, text=log_message, parse_mode='Markdown', disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"[LOG ERROR] Failed to send log: {e}")

async def log_user_registration(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str):
    log = f"🆕 **NEW USER REGISTERED**\n\n👤 **User:** {username}\n🆔 **ID:** `{user_id}`\n⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n📊 **Total Users:** {len(data['users'])}"
    await send_log_to_support(context, log)

async def log_number_purchase(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, country: str, quantity: int, price: int, phone_numbers: list):
    phones_text = "\n".join([f"   • `{phone}`" for phone in phone_numbers])
    log = f"✅ **NUMBER SOLD - SUCCESSFUL**\n\n👤 **Buyer:** {username}\n🆔 **User ID:** `{user_id}`\n🌍 **Country:** {country.upper()}\n📊 **Quantity:** {quantity}\n💰 **Amount:** {price} INR\n\n📱 **Phone Numbers:**\n{phones_text}\n\n⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n💳 **Remaining Balance:** {data['users'][str(user_id)]['balance']} INR\n📦 **Stock Left:** {data['accounts'][country]['quantity']}"
    await send_log_to_support(context, log)

async def log_session_added(context: ContextTypes.DEFAULT_TYPE, country: str, phone: str, has_2fa: bool):
    """Log when owner adds session - ONLY PHONE NUMBER"""
    log = f"➕ **SESSION ADDED**\n\n🌍 **Country:** {country.upper()}\n📱 **Phone:** `{phone}`\n🔐 **2FA:** {'Yes' if has_2fa else 'No'}\n\n⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n📦 **Total Stock:** {data['accounts'][country]['quantity']}"
    await send_log_to_support(context, log)

async def log_country_deleted(context: ContextTypes.DEFAULT_TYPE, country: str, quantity: int, price: int):
    log = f"🗑️ **COUNTRY DELETED**\n\n🌍 **Country:** {country.upper()}\n📊 **Removed:** {quantity} session(s)\n💰 **Price:** {price} INR\n\n⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    await send_log_to_support(context, log)

async def log_coupon_redeemed(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, coupon_code: str, amount: int):
    log = f"🎟️ **COUPON REDEEMED**\n\n👤 **User:** {username}\n🆔 **ID:** `{user_id}`\n🎫 **Coupon:** `{coupon_code}`\n💰 **Amount:** {amount} INR\n\n⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n💳 **New Balance:** {data['users'][str(user_id)]['balance']} INR"
    await send_log_to_support(context, log)

async def log_discount_applied(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, discount_code: str, discount: int):
    log = f"🎟️ **DISCOUNT CODE APPLIED**\n\n👤 **User:** {username}\n🆔 **ID:** `{user_id}`\n🏷️ **Code:** `{discount_code}`\n💰 **Discount:** {discount} INR\n\n⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    await send_log_to_support(context, log)

async def log_payment_submitted(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, amount: int):
    log = f"💳 **PAYMENT SUBMITTED**\n\n👤 **User:** {username}\n🆔 **ID:** `{user_id}`\n💰 **Amount:** {amount} INR\n📸 **Screenshot:** Received\n\n⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n⚠️ **Status:** Waiting for approval"
    await send_log_to_support(context, log)

async def log_payment_approved(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, amount: int):
    log = f"✅ **PAYMENT APPROVED**\n\n👤 **User:** {username}\n🆔 **ID:** `{user_id}`\n💰 **Amount:** {amount} INR\n\n⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n💳 **New Balance:** {data['users'][str(user_id)]['balance']} INR"
    await send_log_to_support(context, log)

async def log_payment_rejected(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, amount: int):
    log = f"❌ **PAYMENT REJECTED**\n\n👤 **User:** {username}\n🆔 **ID:** `{user_id}`\n💰 **Amount:** {amount} INR\n\n⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    await send_log_to_support(context, log)

async def log_broadcast_sent(context: ContextTypes.DEFAULT_TYPE, total: int, success: int, failed: int):
    log = f"📣 **BROADCAST COMPLETED**\n\n👥 **Total Users:** {total}\n✅ **Sent:** {success}\n❌ **Failed:** {failed}\n📊 **Success Rate:** {(success/total*100):.1f}%\n\n⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    await send_log_to_support(context, log)

async def log_otp_fetched(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, country: str, success_count: int, total: int):
    log = f"🔑 **OTP FETCH ATTEMPT**\n\n👤 **User:** {username}\n🆔 **ID:** `{user_id}`\n🌍 **Country:** {country.upper()}\n✅ **Found:** {success_count}/{total}\n\n⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    await send_log_to_support(context, log)

async def log_insufficient_balance(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, required: int, current: int):
    log = f"⚠️ **INSUFFICIENT BALANCE**\n\n👤 **User:** {username}\n🆔 **ID:** `{user_id}`\n💰 **Required:** {required} INR\n💳 **Current:** {current} INR\n❌ **Shortage:** {required - current} INR\n\n⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    await send_log_to_support(context, log)

async def log_balance_added(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, amount: int, new_balance: int):
    """Log when owner adds balance"""
    log = f"➕ **BALANCE ADDED BY OWNER**\n\n👤 **User:** {username}\n🆔 **ID:** `{user_id}`\n💰 **Added:** {amount} INR\n💳 **New Balance:** {new_balance} INR\n\n⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    await send_log_to_support(context, log)

async def log_balance_deducted(context: ContextTypes.DEFAULT_TYPE, user_id: int, username: str, amount: int, new_balance: int):
    """Log when owner deducts balance"""
    log = f"➖ **BALANCE DEDUCTED BY OWNER**\n\n👤 **User:** {username}\n🆔 **ID:** `{user_id}`\n💰 **Deducted:** {amount} INR\n💳 **New Balance:** {new_balance} INR\n\n⏰ **Time:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    await send_log_to_support(context, log)

# ============ END LOGGING SYSTEM ============

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

def is_coupon_used_globally(coupon_code):
    """Check if coupon is already used by ANY user"""
    if "global_used_coupons" not in data:
        data["global_used_coupons"] = []
    return coupon_code in data["global_used_coupons"]

def mark_coupon_used_globally(coupon_code):
    """Mark coupon as used globally (FIRST-USE-ONLY)"""
    if "global_used_coupons" not in data:
        data["global_used_coupons"] = []
    data["global_used_coupons"].append(coupon_code)
    save_data(data)

def is_discount_used_globally(discount_code):
    """Check if discount is already used by ANY user"""
    if "global_used_discounts" not in data:
        data["global_used_discounts"] = []
    return discount_code in data["global_used_discounts"]

def mark_discount_used_globally(discount_code):
    """Mark discount as used globally (FIRST-USE-ONLY)"""
    if "global_used_discounts" not in data:
        data["global_used_discounts"] = []
    data["global_used_discounts"].append(discount_code)
    save_data(data)

# Membership check with cache
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
        membership_cache[user_id] = {"is_member": is_member, "time": current_time}
        return is_member
    except Exception as e:
        logger.error(f"[MEMBERSHIP CHECK ERROR] User {user_id}: {e}")
        return False

async def show_force_join_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show force join message"""
    username = update.effective_user.username or "User"
    text = f"🔒 *Access Restricted!*\n\n👋 *Hello {username}!*\n\n⚠️ *To use this bot, you must join our official channel and group:*\n\n📢 *Support Channel:* Updates & Announcements\n👥 *Support Group:* Help & Community\n\n🔐 *After joining both, click \"✅ Joined\" button!*\n\n💡 *Why join?*\n• Get latest updates & offers\n• 24/7 community support\n• Exclusive deals for members"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=SUPPORT_CHANNEL_LINK)],
        [InlineKeyboardButton("👥 Join Group", url=SUPPORT_GROUP_LINK)],
        [InlineKeyboardButton("✅ Joined - Verify Now", callback_data="verify_join")]
    ])
    if update.message:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
        except:
            await update.callback_query.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')

# Pyrogram Functions
async def create_client(session_string, user_id):
    """Create Pyrogram client"""
    try:
        client = Client(f"temp_session_{user_id}", api_id=API_ID, api_hash=API_HASH, session_string=session_string)
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
                    patterns = [r'(?:code|код)[:\s]+(\d{5,6})', r'\b(\d{5,6})\b']
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
    welcome_text = f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n🔥 *VIRTUAL ACCOUNT STORE* 🔥\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n👋 *Welcome Back, {username}!*\n\n💰 *Balance:* `{get_user_data(user_id)['balance']} INR`\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n✨ *PREMIUM FEATURES* ✨\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n🌍 *Multiple Countries Available*\n⚡ *Instant OTP Delivery*\n✅ *100% Working Sessions*\n🔒 *Secure & Confidential*\n💎 *Premium Quality*\n🚀 *24/7 Support*\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n🎯 *QUICK ACTIONS*\n━━━━━━━━━━━━━━━━━━━━━━━━━━"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🦋 BUY VIRTUAL ACCOUNTS", callback_data="virtual_accounts")],
        [InlineKeyboardButton("💳 MY BALANCE", callback_data=f"my_balance_{user_id}"), InlineKeyboardButton("➕ ADD FUNDS", callback_data="add_funds")],
        [InlineKeyboardButton("📞 SUPPORT", url=SUPPORT_GROUP_LINK)]
    ])
    try:
        if data.get("bot_photo"):
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=data["bot_photo"], caption=welcome_text, reply_markup=keyboard, parse_mode='Markdown')
        else:
            if update.message:
                await update.message.reply_text(welcome_text, reply_markup=keyboard, parse_mode='Markdown')
            elif update.callback_query:
                await update.callback_query.message.reply_text(welcome_text, reply_markup=keyboard, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"[MAIN MENU ERROR] {e}")
        if update.message:
            await update.message.reply_text(welcome_text, reply_markup=keyboard, parse_mode='Markdown')
        elif update.callback_query:
            await update.callback_query.message.reply_text(welcome_text, reply_markup=keyboard, parse_mode='Markdown')

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
        success_text = "✅ *Verification Successful!*\n\n🎉 *Welcome to Virtual Account Store!*\n\n✅ *Channel Joined*\n✅ *Group Joined*\n\n🚀 *Loading main menu...*"
        try:
            await query.edit_message_text(success_text, parse_mode='Markdown')
        except:
            pass
        await show_main_menu(update, context)
    else:
        error_text = "❌ *Verification Failed!*\n\n⚠️ *You must join both channel and group!*\n\n📋 *Steps:*\n1️⃣ Click \"Join Channel\" and \"Join Group\"\n2️⃣ Join both\n3️⃣ Click \"✅ Joined\" again\n\n💡 *Don't leave after joining!*"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Join Channel", url=SUPPORT_CHANNEL_LINK)],
            [InlineKeyboardButton("👥 Join Group", url=SUPPORT_GROUP_LINK)],
            [InlineKeyboardButton("✅ Joined - Verify Now", callback_data="verify_join")]
        ])
        try:
            await query.edit_message_text(error_text, reply_markup=keyboard, parse_mode='Markdown')
        except:
            pass

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
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🦋 VIRTUAL ACCOUNTS", callback_data="virtual_accounts")],
        [InlineKeyboardButton("💳 MY BALANCE", callback_data=f"my_balance_{user_id}")],
        [InlineKeyboardButton("➕ ADD FUNDS", callback_data="add_funds")]
    ])
    welcome_text = f"🔥 *Welcome Back!*\n\n💰 *Your Balance:* `{get_user_data(user_id)['balance']} INR`\n\n🎯 *Choose an option:*"
    try:
        await query.edit_message_text(welcome_text, reply_markup=keyboard, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"[MAIN MENU NAV ERROR] {e}")

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
            keyboard.append([InlineKeyboardButton(f"🦋 {country.upper()} ({info['quantity']} available) - {info['price']} INR", callback_data=f"country_{country}")])
    if not countries:
        keyboard = [[InlineKeyboardButton("📭 No Accounts", callback_data="no_accounts")]]
        text = "📭 *No accounts available currently!*"
    else:
        text = "🌍 *Choose Country:*\n\n" + "\n".join([f"• *{c.upper()}*: {data['accounts'][c]['quantity']} - `{data['accounts'][c]['price']} INR`" for c in countries])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"[SHOW COUNTRIES ERROR] {e}")

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
        try:
            await query.edit_message_text("❌ *Country not found!*", parse_mode='Markdown')
        except:
            pass
        return
    account_info = data["accounts"][country]
    price = account_info["price"]
    balance = get_user_data(user_id)["balance"]
    text = f"📱 *{country.upper()} Virtual Account*\n\n💰 *Price:* `{price} INR`\n📊 *Available:* `{account_info['quantity']}`\n💳 *Your Balance:* `{balance} INR`\n\n✅ *Fresh & Verified*\n✅ *Instant OTP Delivery*\n✅ *100% Safe*"
    keyboard = [
        [InlineKeyboardButton("💳 BUY NUMBER", callback_data=f"buy_number_{country}")],
        [InlineKeyboardButton("🎟 DISCOUNT CODE", callback_data="discount")],
        [InlineKeyboardButton("🔙 Back", callback_data="virtual_accounts")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ]
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"[SHOW ACCOUNT DETAILS ERROR] {e}")

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
    text = f"🛒 *Purchase {country.upper()}*\n\n📊 *Available:* `{available}`\n💰 *Price:* `{price} INR each`\n💳 *Your Balance:* `{balance} INR`\n\n📝 *How many accounts? (1-{available}):*"
    try:
        await query.edit_message_text(text, parse_mode='Markdown')
    except:
        pass
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
            text = f"❌ *Insufficient Balance!*\n\n💰 *Required:* `{total_price} INR`\n💳 *Your Balance:* `{balance} INR`\n\n➕ *Add funds first!*"
            keyboard = [[InlineKeyboardButton("➕ Add Funds", callback_data="add_funds")]]
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
            clear_user_state(user_id)
            return ConversationHandler.END
        confirmation_text = f"🛒 *Confirm Purchase*\n\n📱 *Country:* `{country.upper()}`\n📊 *Quantity:* `{quantity}`\n💰 *Total:* `{total_price} INR`\n💳 *Remaining:* `{balance - total_price} INR`\n\n⚡ *Ready to buy?*"
        keyboard = [
            [InlineKeyboardButton("✅ CONFIRM", callback_data=f"confirm_buy_{country}_{quantity}")],
            [InlineKeyboardButton("❌ CANCEL", callback_data=f"country_{country}")]
        ]
        await update.message.reply_text(confirmation_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
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
    
    text = f"🎉 *Purchase Successful!*\n\n✅ *{quantity} {country.upper()} account(s)!*\n💰 *Deducted:* `{price} INR`\n💳 *Balance:* `{data['users'][str(user_id)]['balance']} INR`\n\n📋 *Your Accounts:*\n"
    for i, session_data in enumerate(purchased_sessions, 1):
        text += f"\n*Account {i}:* `{session_data.get('session', 'N/A')[:30]}...`"
    text += f"\n\n⚡ *Next Steps:*\n1️⃣ Click \"GET NUMBER\"\n2️⃣ Start Telegram login\n3️⃣ Click \"GET OTP\"\n4️⃣ Complete login"
    keyboard = [
        [InlineKeyboardButton("📱 GET NUMBER", callback_data=f"get_number_{user_id}_{len(data['users'][str(user_id)]['purchases'])-1}")],
        [InlineKeyboardButton("🛒 Buy More", callback_data="virtual_accounts")]
    ]
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"[CONFIRM PURCHASE ERROR] {e}")

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
    
    text = f"📱 *Phone Numbers Retrieved!*\n\n*Country:* `{purchase['country'].upper()}`\n*Quantity:* `{purchase['quantity']}`\n\n"
    for i, phone in enumerate(phone_numbers, 1):
        text += f"\n*Account {i}:*\n📞 `{phone}`\n"
    text += f"\n⚡ *Next Steps:*\n1️⃣ Use numbers to login on Telegram\n2️⃣ Click \"GET OTP\" for verification\n3️⃣ Complete login"
    keyboard = [
        [InlineKeyboardButton("🔍 GET OTP", callback_data=f"get_otp_{user_id}_{purchase_index}")],
        [InlineKeyboardButton("✅ LOGIN COMPLETE", callback_data=f"login_complete_{user_id}")]
    ]
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"[GET NUMBER ERROR] {e}")

async def get_otp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Fetch OTP - WITH PHONE NUMBER AND 2FA"""
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
    loading_text = f"🔍 *Fetching OTP...*\n\n*Country:* `{purchase['country'].upper()}`\n*Quantity:* `{purchase['quantity']}`\n\n⏳ *Checking Telegram (777000)...*\n💡 *Make sure you started login!*"
    try:
        await query.edit_message_text(loading_text, parse_mode='Markdown')
    except:
        pass
    
    async def fetch_otp_with_details(i, session_data):
        session_string = session_data.get("session")
        twofa = session_data.get("2fa", None)
        if session_string:
            client = None
            try:
                client = await create_client(session_string, f"{user_id}_{i}_otp")
                if client:
                    phone = await get_phone_number(client)
                    otp = await get_otp_from_telegram(client)
                    await client.stop()
                    if otp:
                        result = f"✅ OTP: `{otp}` - 📱 `{phone}`"
                        if twofa:
                            result += f"\n🔐 2FA: `{twofa}`"
                        return {"status": "success", "otp": otp, "phone": phone, "2fa": twofa, "message": result}
                    return {"status": "not_found", "otp": None, "phone": phone, "2fa": twofa, "message": f"⏳ OTP not found yet - 📱 `{phone}`"}
            except Exception as e:
                if client:
                    try:
                        await client.stop()
                    except:
                        pass
                return {"status": "error", "otp": None, "phone": "Error", "2fa": None, "message": f"❌ Error: {str(e)[:20]}"}
        return {"status": "error", "otp": None, "phone": "N/A", "2fa": None, "message": "❌ No session"}
    
    tasks = [fetch_otp_with_details(i, s) for i, s in enumerate(sessions)]
    otp_results = await asyncio.gather(*tasks)
    
    text = f"🔑 *OTP Retrieval Results*\n\n*Country:* `{purchase['country'].upper()}`\n*Quantity:* `{purchase['quantity']}`\n\n"
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
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"[GET OTP ERROR] {e}")

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
    text = f"💳 *My Balance*\n\n💰 *Current Balance:* `{balance} INR`\n\n📊 *Recent Transactions:*\n"
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
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"[SHOW BALANCE ERROR] {e}")

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
    text = "➕ *Add Funds*\n\n💳 *Choose method:*\n\n1️⃣ *Buy Funds (UPI)* - Instant\n2️⃣ *Coupon Code* - Redeem\n\n💡 *Minimum: 10 INR*"
    keyboard = [
        [InlineKeyboardButton("💸 Buy Funds (UPI)", callback_data="buy_fund")],
        [InlineKeyboardButton("🎟 Coupon Code", callback_data="coupon_code")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"[ADD FUNDS OPTIONS ERROR] {e}")

async def ask_fund_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    text = "💰 *Enter Amount*\n\n💡 *Minimum 10 INR*\n\nExample: `50` or `100`\n\n📝 *Reply with amount:*"
    try:
        await query.edit_message_text(text, parse_mode='Markdown')
    except:
        pass
    set_user_state(user_id, WAITING_FOR_AMOUNT)
    return WAITING_FOR_AMOUNT

async def handle_amount_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle amount input - WITH QR"""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    try:
        amount = int(text)
        if amount < 10:
            await update.message.reply_text("❌ *Minimum 10 INR!*", parse_mode='Markdown')
            return WAITING_FOR_AMOUNT
        data["pending_payments"][str(user_id)] = {"amount": amount, "timestamp": datetime.now().isoformat(), "status": "waiting_screenshot"}
        save_data(data)
        qr_image = generate_upi_qr(amount)
        payment_text = f"💸 *Payment Details*\n\n💰 *Amount:* `{amount} INR`\n👤 *UPI ID:* `{UPI_ID}`\n\n📱 *PAY VIA QR CODE:*\n⬇️ *Scan QR below with any UPI app*\n\nOR\n\n💳 *MANUAL PAYMENT:*\n1. Open any UPI app (GPay/PhonePe/Paytm)\n2. Send `{amount} INR` to: `{UPI_ID}`\n3. Take screenshot of payment\n4. Send screenshot here\n\n⏰ *Processing: 5-10 min*"
        if qr_image:
            await update.message.reply_photo(photo=qr_image, caption=payment_text, parse_mode='Markdown')
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
    text = "🎟 *Enter Coupon Code*\n\nExample: `WELCOME10`\n\n📝 *Reply with code:*"
    try:
        await query.edit_message_text(text, parse_mode='Markdown')
    except:
        pass
    set_user_state(user_id, WAITING_FOR_COUPON)
    return WAITING_FOR_COUPON

async def handle_coupon_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle coupon - FIRST USE ONLY"""
    user_id = update.effective_user.id
    coupon_code = update.message.text.strip().upper()
    username = data["users"][str(user_id)]["username"]
    if coupon_code not in data["coupons"]:
        await update.message.reply_text("❌ *Invalid coupon!*", parse_mode='Markdown')
        clear_user_state(user_id)
        return ConversationHandler.END
    if is_coupon_used_globally(coupon_code):
        await update.message.reply_text("❌ *Coupon already used by someone!*\n\n💡 *This coupon was already redeemed.*", parse_mode='Markdown')
        clear_user_state(user_id)
        return ConversationHandler.END
    coupon = data["coupons"][coupon_code]
    get_user_data(user_id)["balance"] += coupon["amount"]
    mark_coupon_used_globally(coupon_code)
    del data["coupons"][coupon_code]
    save_data(data)
    await log_coupon_redeemed(context, user_id, username, coupon_code, coupon["amount"])
    text = f"✅ *Coupon Redeemed!*\n\n🎟 *Code:* `{coupon_code}`\n💰 *Added:* `{coupon['amount']} INR`\n💳 *Balance:* `{get_user_data(user_id)['balance']} INR`\n\n⚠️ *This coupon is now expired!*"
    keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
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
    caption = f"🔔 *New Payment!*\n\n👤 *User:* {username}\n🆔 *ID:* `{user_id}`\n💰 *Amount:* `{amount} INR`\n⏰ *Time:* {datetime.now().strftime('%H:%M %d/%m')}\n\n🔍 *Please verify!*"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ APPROVE", callback_data=f"approve_fund_{user_id}_{amount}")],
        [InlineKeyboardButton("❌ REJECT", callback_data=f"reject_fund_{user_id}")]
    ])
    try:
        await context.bot.forward_message(chat_id=OWNER_ID, from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
        await context.bot.send_message(chat_id=OWNER_ID, text=caption, reply_markup=keyboard, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"[SCREENSHOT ERROR] {e}")
        try:
            photo_file = await photo.get_file()
            photo_bytes = await photo_file.download_as_bytearray()
            await context.bot.send_photo(chat_id=OWNER_ID, photo=BytesIO(photo_bytes), caption=caption, reply_markup=keyboard, parse_mode='Markdown')
        except Exception as e2:
            logger.error(f"[SCREENSHOT FALLBACK ERROR] {e2}")
            await update.message.reply_text("❌ *Error occurred! Try again by /start*\n\n💡 *Or contact:* @lTZ_ME_ADITYA_02", parse_mode='Markdown')
            return ConversationHandler.END
    await update.message.reply_text("✅ *Screenshot received!*\n\n🔄 *Owner will verify in 5-10 min*\n💳 *Check balance anytime*", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💳 Balance", callback_data=f"my_balance_{user_id}")]]), parse_mode='Markdown')
    data["pending_payments"][str(user_id)] = {"amount": amount, "screenshot": photo.file_id, "timestamp": datetime.now().isoformat(), "status": "submitted"}
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
    await context.bot.send_message(user_id, f"🎉 *Funds Added!*\n\n💰 *Amount:* `{amount} INR`\n💳 *Balance:* `{get_user_data(user_id)['balance']} INR`", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]))
    try:
        await query.edit_message_text(f"✅ *Approved {amount} INR for user {user_id}!*", parse_mode='Markdown')
    except:
        pass

async def reject_fund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("❌ Rejected!")
    user_id = int(query.data.split("_")[2])
    username = data["users"].get(str(user_id), {}).get("username", f"User_{user_id}")
    amount = data["pending_payments"].get(str(user_id), {}).get("amount", 0)
    await log_payment_rejected(context, user_id, username, amount)
    await context.bot.send_message(user_id, "❌ *Payment Rejected!*\n\n💡 *Try again with correct amount*\n📞 *Contact:* @lTZ_ME_ADITYA_02", parse_mode='Markdown')
    if str(user_id) in data["pending_payments"]:
        data["pending_payments"][str(user_id)]["status"] = "rejected"
        save_data(data)
    try:
        await query.edit_message_text(f"❌ *Rejected user {user_id}!*", parse_mode='Markdown')
    except:
        pass

# ============ OWNER /ADD AND /DEDUCT ============
async def owner_add_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner /add command"""
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ *Unauthorized!*", parse_mode='Markdown')
        return ConversationHandler.END
    await update.message.reply_text("➕ *Add Balance*\n\n📝 *Enter User ID:*", parse_mode='Markdown')
    set_user_state(user_id, WAITING_FOR_ADD_USER_ID)
    return WAITING_FOR_ADD_USER_ID

async def handle_add_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user ID for adding balance"""
    owner_id = update.effective_user.id
    if not is_owner(owner_id):
        return ConversationHandler.END
    try:
        target_user_id = int(update.message.text.strip())
        if str(target_user_id) not in data["users"]:
            await update.message.reply_text("❌ *User not found!*", parse_mode='Markdown')
            clear_user_state(owner_id)
            return ConversationHandler.END
        user_info = data["users"][str(target_user_id)]
        username = user_info.get("username", f"User_{target_user_id}")
        balance = user_info.get("balance", 0)
        purchases = len(user_info.get("purchases", []))
        text = f"👤 *User Details*\n\n📛 *Username:* {username}\n🆔 *ID:* `{target_user_id}`\n💰 *Balance:* `{balance} INR`\n📊 *Purchases:* {purchases}\n\n💵 *Enter amount to add:*"
        await update.message.reply_text(text, parse_mode='Markdown')
        set_user_state(owner_id, WAITING_FOR_ADD_AMOUNT, {"target_user_id": target_user_id})
        return WAITING_FOR_ADD_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ *Invalid User ID!*", parse_mode='Markdown')
        return WAITING_FOR_ADD_USER_ID

async def handle_add_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle amount for adding balance"""
    owner_id = update.effective_user.id
    if not is_owner(owner_id):
        return ConversationHandler.END
    try:
        amount = int(update.message.text.strip())
        state = get_user_state(owner_id)
        target_user_id = state["data"]["target_user_id"]
        if amount <= 0:
            await update.message.reply_text("❌ *Amount must be positive!*", parse_mode='Markdown')
            return WAITING_FOR_ADD_AMOUNT
        data["users"][str(target_user_id)]["balance"] += amount
        save_data(data)
        username = data["users"][str(target_user_id)]["username"]
        new_balance = data["users"][str(target_user_id)]["balance"]
        await log_balance_added(context, target_user_id, username, amount, new_balance)
        try:
            await context.bot.send_message(target_user_id, f"🎉 *Balance Credited!*\n\n💰 *Added:* `{amount} INR`\n💳 *New Balance:* `{new_balance} INR`\n\n✨ *Added by Owner*", parse_mode='Markdown')
        except:
            pass
        await update.message.reply_text(f"✅ *Balance Added!*\n\n👤 *User:* {username}\n💰 *Added:* `{amount} INR`\n💳 *New Balance:* `{new_balance} INR`", parse_mode='Markdown')
        clear_user_state(owner_id)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ *Invalid amount!*", parse_mode='Markdown')
        return WAITING_FOR_ADD_AMOUNT

async def owner_deduct_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner /deduct command"""
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ *Unauthorized!*", parse_mode='Markdown')
        return ConversationHandler.END
    await update.message.reply_text("➖ *Deduct Balance*\n\n📝 *Enter User ID:*", parse_mode='Markdown')
    set_user_state(user_id, WAITING_FOR_DEDUCT_USER_ID)
    return WAITING_FOR_DEDUCT_USER_ID

async def handle_deduct_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user ID for deducting balance"""
    owner_id = update.effective_user.id
    if not is_owner(owner_id):
        return ConversationHandler.END
    try:
        target_user_id = int(update.message.text.strip())
        if str(target_user_id) not in data["users"]:
            await update.message.reply_text("❌ *User not found!*", parse_mode='Markdown')
            clear_user_state(owner_id)
            return ConversationHandler.END
        user_info = data["users"][str(target_user_id)]
        username = user_info.get("username", f"User_{target_user_id}")
        balance = user_info.get("balance", 0)
        purchases = len(user_info.get("purchases", []))
        text = f"👤 *User Details*\n\n📛 *Username:* {username}\n🆔 *ID:* `{target_user_id}`\n💰 *Balance:* `{balance} INR`\n📊 *Purchases:* {purchases}\n\n💵 *Enter amount to deduct:*"
        await update.message.reply_text(text, parse_mode='Markdown')
        set_user_state(owner_id, WAITING_FOR_DEDUCT_AMOUNT, {"target_user_id": target_user_id})
        return WAITING_FOR_DEDUCT_AMOUNT
    except ValueError:
        await update.message.reply_text("❌ *Invalid User ID!*", parse_mode='Markdown')
        return WAITING_FOR_DEDUCT_USER_ID

async def handle_deduct_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle amount for deducting balance"""
    owner_id = update.effective_user.id
    if not is_owner(owner_id):
        return ConversationHandler.END
    try:
        amount = int(update.message.text.strip())
        state = get_user_state(owner_id)
        target_user_id = state["data"]["target_user_id"]
        if amount <= 0:
            await update.message.reply_text("❌ *Amount must be positive!*", parse_mode='Markdown')
            return WAITING_FOR_DEDUCT_AMOUNT
        current_balance = data["users"][str(target_user_id)]["balance"]
        if amount > current_balance:
            await update.message.reply_text(f"❌ *Cannot deduct! User balance: {current_balance} INR*", parse_mode='Markdown')
            return WAITING_FOR_DEDUCT_AMOUNT
        data["users"][str(target_user_id)]["balance"] -= amount
        save_data(data)
        username = data["users"][str(target_user_id)]["username"]
        new_balance = data["users"][str(target_user_id)]["balance"]
        await log_balance_deducted(context, target_user_id, username, amount, new_balance)
        try:
            await context.bot.send_message(target_user_id, f"⚠️ *Balance Deducted!*\n\n💰 *Deducted:* `{amount} INR`\n💳 *New Balance:* `{new_balance} INR`\n\n✨ *Deducted by Owner*", parse_mode='Markdown')
        except:
            pass
        await update.message.reply_text(f"✅ *Balance Deducted!*\n\n👤 *User:* {username}\n💰 *Deducted:* `{amount} INR`\n💳 *New Balance:* `{new_balance} INR`", parse_mode='Markdown')
        clear_user_state(owner_id)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ *Invalid amount!*", parse_mode='Markdown')
        return WAITING_FOR_DEDUCT_AMOUNT

# Owner Panel
async def owner_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        if update.message:
            await update.message.reply_text("❌ *Unauthorized!*", parse_mode='Markdown')
        return ConversationHandler.END
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Number", callback_data="owner_addnumber")],
        [InlineKeyboardButton("🗑 Delete Country", callback_data="owner_delete")],
        [InlineKeyboardButton("🎟 Create Discount", callback_data="owner_discount")],
        [InlineKeyboardButton("💰 Create Coupon", callback_data="owner_coupon")],
        [InlineKeyboardButton("📣 Broadcast", callback_data="owner_broadcast")],
        [InlineKeyboardButton("📊 View Payments", callback_data="owner_payments")],
        [InlineKeyboardButton("👥 User Stats", callback_data="owner_stats")],
        [InlineKeyboardButton("📸 Set Bot Photo", callback_data="owner_setdp")],
        [InlineKeyboardButton("🏠 Close", callback_data="main_menu")]
    ])
    text = "🔧 *Owner Panel*\n\n👑 *Welcome Admin!*\n\nChoose action:"
    if update.message:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode='Markdown')
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode='Markdown')
        except:
            pass

async def owner_add_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    text = "➕ *Add Numbers*\n\n📝 *Enter country name:*\n\nExamples: `USA`, `INDIA`, `KENYA`"
    try:
        await query.edit_message_text(text, parse_mode='Markdown')
    except:
        pass
    set_user_state(user_id, WAITING_FOR_COUNTRY)
    return WAITING_FOR_COUNTRY

async def handle_country_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return ConversationHandler.END
    country = update.message.text.strip().upper()
    if country in data["accounts"]:
        existing_info = data["accounts"][country]
        text = f"⚠️ *'{country}' exists!*\n\n📊 *Current:*\n• Price: `{existing_info['price']} INR`\n• Available: `{existing_info['quantity']}`\n\n💡 *Type:*\n• `ADD` - Add more sessions\n• `NEW` - Change price + add\n• `CANCEL` - Cancel"
        await update.message.reply_text(text, parse_mode='Markdown')
        set_user_state(user_id, WAITING_FOR_ADD_MORE_SESSIONS, {"country": country, "price": existing_info['price']})
        return WAITING_FOR_ADD_MORE_SESSIONS
    set_user_state(user_id, WAITING_FOR_PRICE, {"country": country})
    text = f"💰 *Set Price for {country}*\n\n💡 *Enter price in INR:*\n\nExample: `60`"
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
        text = f"🔗 *Add Sessions for {country}*\n\n💰 *Price:* `{old_price} INR`\n\n📝 *Send session string:*"
        await update.message.reply_text(text, parse_mode='Markdown')
        set_user_state(user_id, WAITING_FOR_SESSION, {"country": country, "price": old_price, "mode": "add_more"})
        return WAITING_FOR_SESSION
    elif choice == "NEW":
        text = f"💰 *NEW Price for {country}*\n\n💡 *Old:* `{old_price} INR`\n📝 *Enter new price:*"
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
            data["accounts"][country] = {"price": price, "quantity": 0, "sessions": []}
        else:
            data["accounts"][country]["price"] = price
        save_data(data)
        set_user_state(user_id, WAITING_FOR_SESSION, {"country": country, "price": price})
        response_text = f"🔗 *Add Sessions for {country}*\n\n💰 *Price:* `{price} INR`\n\n📝 *Send session string:*"
        await update.message.reply_text(response_text, parse_mode='Markdown')
        return WAITING_FOR_SESSION
    except ValueError:
        await update.message.reply_text("❌ *Invalid! Numbers only.*", parse_mode='Markdown')
        return WAITING_FOR_PRICE

async def handle_session_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle session input - WITH 2FA PROMPT"""
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return ConversationHandler.END
    text = update.message.text.strip()
    if text == "/skip":
        state = get_user_state(user_id)
        country = state["data"]["country"]
        clear_user_state(user_id)
        await update.message.reply_text(f"✅ *Completed for {country}!*\n\n" + "\n".join([f"• *{c}*: {info['quantity']} - {info['price']} INR" for c, info in data["accounts"].items()]), parse_mode='Markdown')
        return ConversationHandler.END
    state = get_user_state(user_id)
    country = state["data"]["country"]
    price = state["data"]["price"]
    if len(text) < 50:
        await update.message.reply_text("❌ *Session too short!*", parse_mode='Markdown')
        return WAITING_FOR_SESSION
    
    # Store session temporarily
    set_user_state(user_id, WAITING_FOR_2FA, {"country": country, "price": price, "session": text})
    await update.message.reply_text("🔐 *2FA Password?*\n\n📝 *Send 2FA password or `/skip` if none:*", parse_mode='Markdown')
    return WAITING_FOR_2FA

async def handle_2fa_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 2FA input - THEN ADD SESSION"""
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return ConversationHandler.END
    text = update.message.text.strip()
    state = get_user_state(user_id)
    country = state["data"]["country"]
    price = state["data"]["price"]
    session_string = state["data"]["session"]
    
    twofa = None if text == "/skip" else text
    
    # Fetch phone number
    async def get_phone_from_session(session_str):
        try:
            client = await create_client(session_str, f"owner_{user_id}_check")
            if client:
                phone = await get_phone_number(client)
                await client.stop()
                return phone
        except:
            pass
        return "Unknown"
    
    phone = await get_phone_from_session(session_string)
    
    session_data = {"session": session_string, "added": datetime.now().isoformat()}
    if twofa:
        session_data["2fa"] = twofa
    
    data["accounts"][country]["sessions"].append(session_data)
    data["accounts"][country]["quantity"] += 1
    save_data(data)
    
    # Log session added (ONLY PHONE NUMBER)
    await log_session_added(context, country, phone, bool(twofa))
    
    response_text = f"✅ *Added!*\n\n📱 *Country:* `{country}`\n📞 *Phone:* `{phone}`\n🔐 *2FA:* {'Yes' if twofa else 'No'}\n💰 *Price:* `{price} INR`\n📊 *Total:* `{data['accounts'][country]['quantity']}`\n\n💡 *Add another or `/skip`:*"
    await update.message.reply_text(response_text, parse_mode='Markdown')
    
    set_user_state(user_id, WAITING_FOR_SESSION, {"country": country, "price": price})
    return WAITING_FOR_SESSION

# Owner Discount/Coupon - NO LOGS
async def create_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return ConversationHandler.END
    text = "🎟 *Create Discount*\n\n💰 *Enter discount in INR:*\n\nExample: `10` for 10 INR off\n\n⚠️ *FIRST-USE-ONLY (expires after first use)*"
    try:
        await query.edit_message_text(text, parse_mode='Markdown')
    except:
        pass
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
        data["discount_codes"][code] = {"discount": discount, "created": datetime.now().isoformat()}
        save_data(data)
        # NO LOG FOR DISCOUNT CREATION
        response_text = f"✅ *Discount Created!*\n\n🎟 *Code:* `{code}`\n💰 *Discount:* `{discount} INR`\n📊 *Usage:* First-use-only\n\n*Copy:* `{code}`"
        keyboard = [[InlineKeyboardButton("🏠 Panel", callback_data="owner_panel")]]
        await update.message.reply_text(response_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
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
    text = "💰 *Create Coupon*\n\n💵 *Enter amount in INR:*\n\nExample: `50` for 50 INR\n\n⚠️ *FIRST-USE-ONLY (expires after first use)*"
    try:
        await query.edit_message_text(text, parse_mode='Markdown')
    except:
        pass
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
        data["coupons"][code] = {"amount": amount, "created": datetime.now().isoformat()}
        save_data(data)
        # NO LOG FOR COUPON CREATION
        response_text = f"✅ *Coupon Created!*\n\n🎟 *Code:* `{code}`\n💰 *Amount:* `{amount} INR`\n📊 *Usage:* First-use-only\n\n*Copy:* `{code}`"
        keyboard = [[InlineKeyboardButton("🏠 Panel", callback_data="owner_panel")]]
        await update.message.reply_text(response_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
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
    text = f"📣 *Broadcast Message*\n\n👥 *Total Users:* `{len(data['users'])}`\n\n📝 *Type your message:*\n\n💡 *Supports:*\n• Text formatting (Markdown)\n• Emojis\n• Line breaks\n\n⚠️ *This will send to ALL users!*"
    try:
        await query.edit_message_text(text, parse_mode='Markdown')
    except:
        pass
    set_user_state(user_id, WAITING_FOR_BROADCAST_MESSAGE)
    return WAITING_FOR_BROADCAST_MESSAGE

async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return ConversationHandler.END
    broadcast_message = update.message.text
    total_users = len(data['users'])
    confirmation_text = f"📣 *Confirm Broadcast*\n\n👥 *Recipients:* `{total_users} users`\n\n📝 *Message Preview:*\n{broadcast_message[:500]}{'...' if len(broadcast_message) > 500 else ''}\n\n⚠️ *Send to all users?*"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ SEND", callback_data=f"broadcast_confirm")],
        [InlineKeyboardButton("❌ CANCEL", callback_data="owner_panel")]
    ])
    await update.message.reply_text(confirmation_text, reply_markup=keyboard, parse_mode='Markdown')
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
        try:
            await query.edit_message_text("❌ *No message found!*", parse_mode='Markdown')
        except:
            pass
        return
    total_users = len(data['users'])
    success_count = 0
    failed_count = 0
    progress_text = f"📤 *Broadcasting...*\n\n👥 *Total:* `{total_users}`\n✅ *Sent:* `0`\n❌ *Failed:* `0`\n\n⏳ *Please wait...*"
    try:
        await query.edit_message_text(progress_text, parse_mode='Markdown')
    except:
        pass
    for user_id_str in data['users'].keys():
        try:
            target_user_id = int(user_id_str)
            await context.bot.send_message(chat_id=target_user_id, text=f"📣 *Broadcast Message*\n\n{broadcast_message}", parse_mode='Markdown')
            success_count += 1
            if success_count % 10 == 0:
                progress_text = f"📤 *Broadcasting...*\n\n👥 *Total:* `{total_users}`\n✅ *Sent:* `{success_count}`\n❌ *Failed:* `{failed_count}`\n\n⏳ *In progress...*"
                try:
                    await query.edit_message_text(progress_text, parse_mode='Markdown')
                except:
                    pass
            await asyncio.sleep(0.05)
        except Exception as e:
            failed_count += 1
            logger.error(f"[BROADCAST ERROR] User {user_id_str}: {e}")
    await log_broadcast_sent(context, total_users, success_count, failed_count)
    final_text = f"✅ *Broadcast Complete!*\n\n👥 *Total:* `{total_users}`\n✅ *Sent:* `{success_count}`\n❌ *Failed:* `{failed_count}`\n\n📊 *Success Rate:* `{(success_count/total_users*100):.1f}%`"
    keyboard = [[InlineKeyboardButton("🏠 Panel", callback_data="owner_panel")]]
    try:
        await query.edit_message_text(final_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except:
        pass
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
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        except:
            pass
        return
    keyboard = []
    for country in countries:
        keyboard.append([InlineKeyboardButton(f"🗑 {country.upper()}", callback_data=f"delete_confirm_{country}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="owner_panel")])
    text = "🗑 *Delete Country*\n\n⚠️ *This removes all accounts!*\n\nChoose country:"
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except:
        pass

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
        text = f"✅ *Deleted!*\n\n📱 *Country:* `{country.upper()}`\n📊 *Removed:* `{quantity}`\n💰 *Price:* `{price} INR`"
    else:
        text = f"❌ *'{country}' not found!*"
    keyboard = [[InlineKeyboardButton("🏠 Panel", callback_data="owner_panel")]]
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except:
        pass

# Owner View Payments
async def owner_view_payments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return
    pending_payments = {uid: info for uid, info in data["pending_payments"].items() if info["status"] == "submitted"}
    if not pending_payments:
        text = "📭 *No pending payments!*"
        keyboard = [[InlineKeyboardButton("🏠 Panel", callback_data="owner_panel")]]
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        except:
            pass
        return
    text = "💳 *Pending Payments*\n\n"
    keyboard = []
    for payment_user_id, info in list(pending_payments.items())[:5]:
        username = data["users"].get(str(payment_user_id), {}).get("username", f"User_{payment_user_id}")
        amount = info["amount"]
        time = datetime.fromisoformat(info["timestamp"]).strftime('%H:%M %d/%m')
        text += f"👤 *{username}*\n💰 `{amount} INR` - `{time}`\n\n"
        keyboard.append([InlineKeyboardButton(f"🔍 {username} - {amount} INR", callback_data=f"review_payment_{payment_user_id}")])
    keyboard.append([InlineKeyboardButton("🏠 Panel", callback_data="owner_panel")])
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except:
        pass

# Owner Stats
async def owner_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return
    total_users = len(data["users"])
    total_balance = sum(user["balance"] for user in data["users"].values())
    total_revenue = sum(purchase["price"] for user in data["users"].values() for purchase in user["purchases"] if purchase.get("status") == "completed")
    available_accounts = sum(info["quantity"] for info in data["accounts"].values())
    text = f"📊 *Bot Statistics*\n\n👥 *Total Users:* `{total_users}`\n💰 *User Balance:* `{total_balance} INR`\n💵 *Revenue:* `{total_revenue} INR`\n\n📱 *Available:* `{available_accounts}`\n\n🌍 *By Country:*\n"
    for country, info in data["accounts"].items():
        if info["quantity"] > 0:
            text += f"\n• *{country}*: `{info['quantity']}` - `{info['price']} INR`"
    text += f"\n\n⏰ `{datetime.now().strftime('%H:%M %d/%m/%Y')}`"
    keyboard = [[InlineKeyboardButton("🏠 Panel", callback_data="owner_panel")]]
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except:
        pass

# Set Bot Photo
async def set_bot_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        if update.message:
            await update.message.reply_text("❌ *Unauthorized!*", parse_mode='Markdown')
        return
    if update.message:
        await update.message.reply_text("📸 *Send bot picture:*\n\n💡 *JPG/PNG, 512x512*", parse_mode='Markdown')
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text("📸 *Send bot picture:*\n\n💡 *JPG/PNG, 512x512*", parse_mode='Markdown')
        except:
            pass
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
    await update.message.reply_text("✅ *Bot photo updated!*\n\n📸 *Restart bot to see*", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Panel", callback_data="owner_panel")]]), parse_mode='Markdown')
    clear_user_state(user_id)
    return ConversationHandler.END

# Discount Application - FIRST USE ONLY
async def apply_discount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    text = "🎟 *Apply Discount*\n\n💡 *Enter code:*\n\nExample: `DISCOUNT1234`"
    try:
        await query.edit_message_text(text, parse_mode='Markdown')
    except:
        pass
    set_user_state(user_id, WAITING_FOR_DISCOUNT_CODE)
    return WAITING_FOR_DISCOUNT_CODE

async def handle_discount_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle discount - FIRST USE ONLY"""
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
    if is_discount_used_globally(code):
        await update.message.reply_text("❌ *Discount already used by someone!*\n\n💡 *This discount was already redeemed.*", parse_mode='Markdown')
        clear_user_state(user_id)
        return ConversationHandler.END
    discount_info = data["discount_codes"][code]
    discount_amount = discount_info["discount"]
    mark_discount_used_globally(code)
    del data["discount_codes"][code]
    save_data(data)
    await log_discount_applied(context, user_id, username, code, discount_amount)
    user_state = get_user_state(user_id)
    if "discount" not in user_state["data"]:
        user_state["data"]["discount"] = 0
    user_state["data"]["discount"] += discount_amount
    set_user_state(user_id, user_state["state"], user_state["data"])
    text = f"✅ *Discount Applied!*\n\n🎟 *Code:* `{code}`\n💰 *Discount:* `{discount_amount} INR`\n💎 *Total Discount:* `{user_state['data']['discount']} INR`\n\n⚠️ *This code is now expired!*"
    keyboard = [[InlineKeyboardButton("🛒 Shop", callback_data="virtual_accounts")]]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    clear_user_state(user_id)
    return ConversationHandler.END

# Login Complete
async def login_complete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("✅ Verified!")
    text = "🎉 *Login Complete!*\n\n✅ *Account activated!*\n✅ *Ready to use!*\n\n💡 *Keep sessions secure*\n\n⭐ *Thank you!*"
    keyboard = [
        [InlineKeyboardButton("🛒 Buy More", callback_data="virtual_accounts")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ]
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except:
        pass

# No Accounts
async def no_accounts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "📭 *No Accounts Available*\n\n😔 *Out of stock!*\n\n⏰ *Check back in 30 min*"
    keyboard = [
        [InlineKeyboardButton("➕ Add Funds", callback_data="add_funds")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]
    ]
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except:
        pass

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
    except (TimedOut, NetworkError) as e:
        logger.error(f"[NETWORK ERROR] {e}")
        await query.answer("⚠️ Network error, try again!", show_alert=True)
    except BadRequest as e:
        logger.error(f"[BAD REQUEST] {e}")
    except Exception as e:
        logger.error(f"[BUTTON ERROR] {e}")
        await query.answer("❌ Error! Try /start", show_alert=True)

# Error Handler
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text("❌ *Error occurred! Try again by /start*\n\n💡 *Or contact:* @lTZ_ME_ADITYA_02", parse_mode='Markdown')
        except:
            pass

# Global fallback
async def global_text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    state_info = get_user_state(user_id)
    current_state = state_info["state"]
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
    elif current_state == WAITING_FOR_ADD_USER_ID:
        return await handle_add_user_id(update, context)
    elif current_state == WAITING_FOR_ADD_AMOUNT:
        return await handle_add_amount(update, context)
    elif current_state == WAITING_FOR_DEDUCT_USER_ID:
        return await handle_deduct_user_id(update, context)
    elif current_state == WAITING_FOR_DEDUCT_AMOUNT:
        return await handle_deduct_amount(update, context)
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
            CommandHandler("add", owner_add_balance_command),
            CommandHandler("deduct", owner_deduct_balance_command),
            CallbackQueryHandler(button_handler)
        ],
        states={
            WAITING_FOR_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount_input)],
            WAITING_FOR_COUPON: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_coupon_input)],
            WAITING_FOR_SCREENSHOT: [MessageHandler(filters.PHOTO, handle_screenshot)],
            WAITING_FOR_COUNTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_country_input)],
            WAITING_FOR_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_price_input)],
            WAITING_FOR_SESSION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_session_input)],
            WAITING_FOR_2FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_2fa_input)],
            WAITING_FOR_DISCOUNT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_discount_input)],
            WAITING_FOR_COUPON_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_coupon_input_owner)],
            WAITING_FOR_DISCOUNT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_discount_code)],
            WAITING_FOR_BOT_PHOTO: [MessageHandler(filters.PHOTO, handle_photo_owner)],
            WAITING_FOR_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quantity_input)],
            WAITING_FOR_ADD_MORE_SESSIONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_more_choice)],
            WAITING_FOR_BROADCAST_MESSAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast_message)],
            WAITING_FOR_ADD_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_user_id)],
            WAITING_FOR_ADD_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_amount)],
            WAITING_FOR_DEDUCT_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_deduct_user_id)],
            WAITING_FOR_DEDUCT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_deduct_amount)],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("panel", owner_panel),
            CommandHandler("add", owner_add_balance_command),
            CommandHandler("deduct", owner_deduct_balance_command),
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
    print("🔥 VIRTUAL ACCOUNT BOT - FULLY FIXED! 🔥")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"\n👑 Owner: {OWNER_ID}")
    print(f"📊 Users: {len(data['users'])}")
    print(f"🌍 Countries: {len(data['accounts'])}")
    print(f"\n✅ ALL FEATURES FIXED:")
    print("   • ✅ /add and /deduct commands")
    print("   • ✅ 2FA handling in session add")
    print("   • ✅ OTP with phone number + 2FA")
    print("   • ✅ First-use-only coupons/discounts")
    print("   • ✅ No logs for coupon/discount creation")
    print("   • ✅ Button error handling")
    print("   • ✅ Session log shows phone, not session")
    print(f"\n🔐 FORCE JOIN ENABLED!")
    print(f"📢 Channel: {SUPPORT_CHANNEL_LINK}")
    print(f"👥 Group: {SUPPORT_GROUP_LINK}")
    print(f"\n📝 LOGGING TO: {SUPPORT_GROUP_ID}")
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🚀 Bot is LIVE! Press Ctrl+C to stop.")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == '__main__':
    main()
