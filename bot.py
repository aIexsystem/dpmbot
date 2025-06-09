#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

from mailslurp_client import Configuration, ApiClient
from mailslurp_client.api.inbox_controller_api import InboxControllerApi
from mailslurp_client.api.wait_for_controller_api import WaitForControllerApi

import config

# ─── Logging ────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Data file ──────────────────────────────────────────────────
DATA_FILE = "data.json"
def load_data():
    if not os.path.exists(DATA_FILE):
        data = {"counter": 0, "chats": {}}
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)
        return data
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_next_counter(data):
    data["counter"] += 1
    save_data(data)
    return data["counter"]

# ─── Bot handlers ──────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[ InlineKeyboardButton("Create Mail", callback_data="create_mail") ]]
    await update.message.reply_text(
        f"Hello! Press “Create Mail” to generate a new mailbox on the {config.DOMAIN_NAME} domain.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = load_data()
    chat_id = str(query.message.chat.id)
    action  = query.data

    # prepare MailSlurp client
    cfg = Configuration()
    cfg.api_key["x-api-key"] = config.MAILSLURP_API_KEY

    with ApiClient(cfg) as api_client:
        inbox_api    = InboxControllerApi(api_client)
        wait_api     = WaitForControllerApi(api_client)

        if action in ("create_mail", "change_mail"):
            # 1) CREATE / CHANGE mailbox
            num = get_next_counter(data)
            email_addr = f"admin{num}@{config.DOMAIN_NAME}"
            try:
                inbox = inbox_api.create_inbox(email_address=email_addr)
                data["chats"][chat_id] = {
                    "inbox_id": inbox.id,
                    "email":    inbox.email_address
                }
                save_data(data)

                text = (
                    f"🆕 New mailbox created:\n"
                    f"Email: {inbox.email_address}\n"
                    f"Inbox ID: {inbox.id}"
                )
                buttons = [
                    [
                        InlineKeyboardButton("Change Mail", callback_data="change_mail"),
                        InlineKeyboardButton("Get OTP",    callback_data="get_otp")
                    ]
                ]
                await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
                logger.info(f"Created inbox {inbox.email_address} for chat {chat_id}")

            except Exception as e:
                logger.exception(f"Error creating inbox: {e}")
                await query.message.reply_text(
                    "❌ Failed to create mailbox. Check logs."
                )

        elif action == "get_otp":
            # 2) FETCH latest email via wait_for_latest_email
            if chat_id not in data["chats"]:
                await query.message.reply_text("Please create a mailbox first.")
                return

            inbox_id = data["chats"][chat_id]["inbox_id"]
            try:
                # wait_for_latest_email will poll up to 30 seconds
                email = wait_api.wait_for_latest_email(
                    inbox_id=inbox_id,
                    timeout=30000,       # millis
                    unread_only=True
                )
            except Exception as e:
                logger.exception(f"Error waiting for email in {inbox_id}: {e}")
                await query.message.reply_text(
                    "❌ Error fetching email. Make sure an email has arrived."
                )
                return

            # build response
            subject = email.subject     or "<no subject>"
            sender  = email.from_       or "<unknown sender>"
            body    = email.body        or "<empty body>"

            resp = (
                f"✉️ Latest email:\n\n"
                f"Subject: {subject}\n"
                f"From: {sender}\n\n"
                f"Content:\n{body}"
            )
            await query.message.reply_text(resp)
            logger.info(f"Delivered email from {inbox_id} to chat {chat_id}")

        else:
            await query.message.reply_text("❓ Unknown command. Please /start again.")

# ─── Error handler ──────────────────────────────────────────────
async def error_handler(update, context):
    logger.error("Update failed", exc_info=context.error)

# ─── Main ──────────────────────────────────────────────────────
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
