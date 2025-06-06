#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
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
from mailslurp_client.api.email_controller_api import EmailControllerApi

import config


# ------------------------ Logging Setup ------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ------------------------ Data File Handling ------------------------
DATA_FILE = "data.json"

def load_data():
    """
    Load the dictionary from data.json. If it doesn't exist,
    create it with initial values {"counter": 0, "chats": {}}.
    """
    if not os.path.exists(DATA_FILE):
        data = {"counter": 0, "chats": {}}
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)
        return data

    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    """
    Save the dictionary `data` back into data.json.
    """
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_next_counter(data):
    """
    Increment data["counter"] by 1, save, and return the new value.
    """
    data["counter"] += 1
    save_data(data)
    return data["counter"]

# ------------------------ Bot Handlers ------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /start command. Send a button labeled "Create Mail".
    """
    keyboard = [
        [InlineKeyboardButton("Create Mail", callback_data="create_mail")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Hello! Press “Create Mail” to generate a new mailbox on the {config.DOMAIN_NAME} domain.",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle inline button presses:
      - create_mail  → create a new inbox and show its address/ID
      - change_mail  → generate the next address in sequence
      - get_otp      → fetch the latest email (OTP/code) from the current inbox
    """
    query = update.callback_query
    await query.answer()  # Acknowledge the callback so Telegram stops showing the “Loading…” spinner.

    data = load_data()
    chat_id = str(query.message.chat.id)
    action = query.data
    logger.info(f"Button pressed: {action} in chat {chat_id}")

    # Prepare MailSlurp configuration
    configuration = Configuration()
    configuration.api_key["x-api-key"] = config.MAILSLURP_API_KEY

    with ApiClient(configuration) as api_client:
        inbox_ctrl = InboxControllerApi(api_client)
        email_ctrl = EmailControllerApi(api_client)

        # 1) CREATE or CHANGE Mail
        if action in ("create_mail", "change_mail"):
            try:
                # Get next sequential number (1, 2, 3, …)
                num = get_next_counter(data)
                email_addr = f"admin{num}@{config.DOMAIN_NAME}"

                # Create the inbox by passing email_address directly:
                inbox = inbox_ctrl.create_inbox(email_address=email_addr)

                # Save inbox_id, email, and number for this chat
                data["chats"][chat_id] = {
                    "inbox_id": inbox.id,
                    "email": inbox.email_address,
                    "number": num
                }
                save_data(data)

                # Reply to the user with a new message (not editing the old one)
                text = (
                    f"🆕 New mailbox created:\n"
                    f"Email: {inbox.email_address}\n"
                    f"Inbox ID: {inbox.id}"
                )
                buttons = [
                    [
                        InlineKeyboardButton("Change Mail", callback_data="change_mail"),
                        InlineKeyboardButton("Get OTP", callback_data="get_otp")
                    ]
                ]
                await query.message.reply_text(
                    text,
                    reply_markup=InlineKeyboardMarkup(buttons)
                )
                logger.info(f"Created inbox {inbox.email_address} (ID={inbox.id}) for chat {chat_id}")

            except Exception as e:
                # If anything goes wrong in MailSlurp, log + inform the user
                logger.exception(f"Failed to create/change inbox for chat {chat_id}: {e!r}")
                await query.message.reply_text(
                    "❌ An error occurred while creating the mailbox. "
                    "Please check the server logs for details."
                )

        # 2) GET OTP (latest email content)
        elif action == "get_otp":
            if chat_id not in data["chats"]:
                await query.message.reply_text(
                    "Please create a mailbox first by pressing “Create Mail.”"
                )
                return

            inbox_id = data["chats"][chat_id]["inbox_id"]
            try:
                # Fetch the single most-recent email
                emails = email_ctrl.get_emails_for_inbox(
                    inbox_id=inbox_id,
                    limit=1,
                    sort="DESC"
                )
            except Exception as e:
                logger.exception(f"Error fetching emails for inbox {inbox_id}: {e!r}")
                await query.message.reply_text(
                    "❌ Error while fetching emails from MailSlurp. "
                    "Please check the logs."
                )
                return

            if not emails:
                await query.message.reply_text("📭 There are no emails in the inbox yet.")
                return

            latest = emails[0]
            try:
                full_email = email_ctrl.get_email(latest.id)
            except Exception as e:
                logger.exception(f"Error retrieving email ID {latest.id}: {e!r}")
                await query.message.reply_text(
                    "❌ Failed to retrieve the full email. Please try again."
                )
                return

            subject = full_email.subject or "<no subject>"
            sender = full_email.from_ or "<unknown sender>"
            body = full_email.body or "<empty email body>"

            text = (
                f"✉️ Latest email:\n\n"
                f"Subject: {subject}\n"
                f"From: {sender}\n\n"
                f"Content:\n{body}"
            )
            await query.message.reply_text(text)
            logger.info(f"Sent latest email from inbox {inbox_id} to chat {chat_id}")

        else:
            # Unexpected callback_data—unlikely, but handle gracefully
            logger.warning(f"Unknown callback_data received: {action}")
            await query.message.reply_text("❓ Unknown command. Please try /start again.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """
    Log any exception that occurs while handling an update.
    """
    logger.error("Exception while handling an update:", exc_info=context.error)

# ------------------------ Main Entry Point ------------------------
def main():
    # Ensure data.json exists (or create it if missing)
    _ = load_data()

    # Build the Telegram bot application
    app = ApplicationBuilder().token(config.TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_error_handler(error_handler)

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()