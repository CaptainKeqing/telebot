import logging

from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, Application, ContextTypes, CallbackQueryHandler

from grocery_manager import GroceryManager, UserState

logger = logging.getLogger(__name__)
TOKEN_FILE = "bot_token.txt"
BOT_NAME = "@ddonobot"

GM = GroceryManager()

# COMMANDS
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Hello! I'm donobot.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("How to use me:\n\n" \
    "I am a grocery helper bot. Use /need to begin adding groceries. Then, just tell me what you want!\n" \
    "Use /done to finish adding groceries.\n\n" \
    "To display your current list, use /display\n\n"
    "To remove groceries, do /remove <indexes separated by space>\n"
    )

# ERRORS
async def error(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"Update {update} cause error {context.error.with_traceback(None)}")

# MESSAGE HANDLING
async def handle_response(user_msg: str, user: int, update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    await GM.handle_message(user_msg, update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    message_type: str = update.message.chat.type # group or private
    text: str = update.message.text
    user_id: int = update.effective_user.id

    print(f"User {user_id} said {text}")

    if message_type.lower() == "group" or "supergroup":
        # This is a QOL feature for active users to not need to Tag the bot
        all_users = GM.userStatesInChat.get(str(update.effective_chat.id), dict())
        active_users = set(user_id for user_id, user_state in all_users.items() if user_state == UserState.IN_NEED)

        if BOT_NAME in text or user_id in active_users:
            await handle_response(text.replace(BOT_NAME,""), user_id, update, context)
        else:
            return

    elif message_type.lower() == "private":
        await handle_response(text, user_id, update, context)
    else:
        print("Unknown type of chat incoming. Ignoring")

def main() -> None:
    with open(TOKEN_FILE, "r") as f:
        TOKEN = f.readline().strip()

    print("Bot starting...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))

    # GM commands
    app.add_handler(CommandHandler("need", GM.need_command))
    app.add_handler(CommandHandler("done", GM.done_command))
    app.add_handler(CommandHandler("remove", GM.remove_command))
    app.add_handler(CommandHandler("clear", GM.clear_command))
    app.add_handler(CommandHandler("display", GM.display_command))

    app.add_handler(MessageHandler(filters.TEXT, handle_message))

    app.add_handler(CallbackQueryHandler(GM.onInlineButtonPress))
    app.add_error_handler(error)

    print("Polling...")
    app.run_polling(poll_interval=0.1)

    # On app shutdown
    print("GM saving...")
    GM.save()


if __name__ == '__main__':
    main()