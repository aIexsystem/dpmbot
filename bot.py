#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import re
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

import mailslurp_client
from mailslurp_client import Configuration, ApiClient
from mailslurp_client.api.inbox_controller_api import InboxControllerApi
from mailslurp_client.api.wait_for_controller_api import WaitForControllerApi

import config

# ─── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Data persistence ───────────────────────────────────────────
DATA_FILE = "data.json"
def load_data():
    if not os.path.exists(DATA_FILE):
        init = {"counter": 0, "chats": {}}
        with open(DATA_FILE, "w") as f:
            json.dump(init, f, indent=2)
        return init
    return json.load(open(DATA_FILE))

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_next_counter(data):
    data["counter"] += 1
    save_data(data)
    return data["counter"]

# ─── /start handler ───────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton("Create Mail", callback_data="create_mail")]]
    await update.message.reply_text(
        f"📬 Press “Create Mail” to generate a new @{config.DOMAIN_NAME} address.",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ─── button handler ────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    data    = load_data()
    chat_id = str(query.message.chat.id)
    action  = query.data

    # MailSlurp setup
    cfg = Configuration()
    cfg.api_key["x-api-key"] = config.MAILSLURP_API_KEY

    with ApiClient(cfg) as api_client:
        inbox_api = InboxControllerApi(api_client)
        wait_api  = WaitForControllerApi(api_client)

        # 1) create_mail / change_mail
        if action in ("create_mail", "change_mail"):
            num        = get_next_counter(data)
            addr       = f"admin{num}@{config.DOMAIN_NAME}"
            try:
                inbox = inbox_api.create_inbox(email_address=addr)
                data["chats"][chat_id] = {"inbox_id": inbox.id}
                save_data(data)
                text = f"✅ Inbox created:\n{inbox.email_address}\nID: {inbox.id}"
                kb = [
                    [ InlineKeyboardButton("Change Mail", callback_data="change_mail"),
                      InlineKeyboardButton("Get OTP",    callback_data="get_otp") ]
                ]
                await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))
                logger.info(f"Created inbox {inbox.id} for chat {chat_id}")
            except Exception as e:
                logger.exception("Failed to create inbox")
                await query.message.reply_text("❌ Error creating mailbox.")

        # 2) get_otp
        elif action == "get_otp":
            if chat_id not in data["chats"]:
                await query.message.reply_text("⏳ Press Create Mail first.")
                return

            inbox_id = data["chats"][chat_id]["inbox_id"]
            try:
                # wait up to 15s for latest email
                email = wait_api.wait_for_latest_email(
                    inbox_id=inbox_id,
                    timeout=15000,   # ms
                    unread_only=True
                )
            except mailslurp_client.exceptions.ApiException as e:
                logger.exception("Error waiting for email")
                await query.message.reply_text("❌ No email received yet.")
                return

            # extract 6-digit OTP
            body = email.body or ""
            logger.info(f"Full email body:\n{body}")  # debug log
            m = re.search(r"\b\d{6}\b", body)
            if m:
                await query.message.reply_text(f"🔑 Your OTP: `{m.group(0)}`", parse_mode="Markdown")
            else:
                await query.message.reply_text("❌ No 6-digit code found.")

        else:
            await query.message.reply_text("❓ Unknown command.")

# ─── error handler ─────────────────────────────────────────────
async def error_handler(update, context):
    logger.error("Update failed", exc_info=context.error)

# ─── main ──────────────────────────────────────────────────────
def main():
    _ = load_data()
    app = ApplicationBuilder().token(config.TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_error_handler(error_handler)

    print("Bot is running…")
    app.run_polling()

if __name__ == "__main__":
    main()
