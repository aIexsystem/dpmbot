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
from mailslurp_client.api.email_controller_api import EmailControllerApi

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
        init = {"counter": 0, "chats": {}}
        with open(DATA_FILE, "w") as f:
            json.dump(init, f, indent=2)
        return init
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
    query   = update.callback_query
    await query.answer()
    data    = load_data()
    chat_id = str(query.message.chat.id)
    action  = query.data

    # Setup MailSlurp client
    cfg = Configuration()
    cfg.api_key["x-api-key"] = config.MAILSLURP_API_KEY

    with ApiClient(cfg) as api_client:
        inbox_api = InboxControllerApi(api_client)
        email_api = EmailControllerApi(api_client)

        # CREATE or CHANGE mail
        if action in ("create_mail", "change_mail"):
            num        = get_next_counter(data)
            email_addr = f"admin{num}@{config.DOMAIN_NAME}"
            try:
                inbox = inbox_api.create_inbox(email_address=email_addr)
                data["chats"][chat_id] = {"inbox_id": inbox.id, "email": inbox.email_address}
                save_data(data)

                text = (
                    f"🆕 New mailbox created:\n"
                    f"Email: {inbox.email_address}\n"
                    f"Inbox ID: {inbox.id}"
                )
                buttons = [[
                    InlineKeyboardButton("Change Mail", callback_data="change_mail"),
                    InlineKeyboardButton("Get OTP",    callback_data="get_otp"),
                ]]
                await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
                logger.info(f"Created inbox {inbox.email_address} for chat {chat_id}")

            except Exception as e:
                logger.exception(f"Failed to create/change inbox: {e}")
                await query.message.reply_text(
                    "❌ An error occurred creating the mailbox. Check logs."
                )

        # GET OTP (latest email)
        elif action == "get_otp":
            if chat_id not in data["chats"]:
                await query.message.reply_text("Please press “Create Mail” first.")
                return

            inbox_id = data["chats"][chat_id]["inbox_id"]
            try:
                # fetch the most recent email
                emails = email_api.get_emails_for_inbox(
                    inbox_id=inbox_id,
                    limit=1,
                    sort="DESC"
                )
            except Exception as e:
                logger.exception(f"Error fetching emails: {e}")
                await query.message.reply_text("❌ Error fetching emails. See logs.")
                return

            if not emails:
                await query.message.reply_text("📭 No emails in the inbox yet.")
                return

            latest = emails[0]
            try:
                full = email_api.get_email(latest.id)
            except Exception as e:
                logger.exception(f"Error retrieving email: {e}")
                await query.message.reply_text("❌ Error retrieving the full email.")
                return

            # Extract everything
            subject   = full.subject            or "<no subject>"
            headers   = full.headers or {}
            sender    = headers.get("From", headers.get("from", "<unknown sender>"))
            to_addr   = headers.get("To",   headers.get("to",   "<unknown recipient>"))
            cc_list   = headers.get("Cc",   "")
            body_text = full.body               or "<empty body>"
            body_html = full.html_body          or ""
            attachment_info = ", ".join(a.name for a in (full.attachments or []))

            reply = [
                f"✉️ *Subject:* {subject}",
                f"*From:* {sender}",
                f"*To:* {to_addr}",
            ]
            if cc_list:
                reply.append(f"*Cc:* {cc_list}")
            if attachment_info:
                reply.append(f"*Attachments:* {attachment_info}")
            reply.append("\n*Body (text):*\n" + body_text)
            if body_html:
                reply.append("\n*Body (HTML):*\n" + body_html)

            await query.message.reply_text(
                "\n".join(reply),
                parse_mode="Markdown"
            )
            logger.info(f"Delivered email from inbox {inbox_id} to chat {chat_id}")

        else:
            await query.message.reply_text("❓ Unknown action. Please /start again.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
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
