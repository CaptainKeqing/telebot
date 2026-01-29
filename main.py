import logging
import pickle

from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, Application, ContextTypes

from grocery_manager import GroceryManager

logger = logging.getLogger(__name__)
isAngry = False
TOKEN_FILE = "bot_token.txt"
BOT_NAME = "@ddonobot"

GM = GroceryManager()
managers = [GM]

# COMMANDS
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Hello! I'm donobot.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("All I do is echo what you say. If you are kind to me, I will respond" \
    " kindly! If you start shouting... well, you get the idea.")

async def sorry_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global isAngry
    isAngry = False
    await update.message.reply_text("I accept your apology.")


# GroceryManager commands
async def need_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context._user_id
    print(f"User {user} starting to add items...")
    response = GM.handle_need_command(user)
    await update.message.reply_text(response)

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context._user_id
    print(f"User {user} is done...")
    response = GM.handle_done_command(user)
    await update.message.reply_text(response)

async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context._user_id
    args = context.args
    print(f"User {user} is removing... {args}")
    print(f"Exp. {context._user_id}")
    response = GM.handle_remove_command(user, args)
    await update.message.reply_text(response)

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context._user_id
    print(f"User {user} is clearing grocery list...")
    response = GM.handle_clear_command(user)
    await update.message.reply_text(response)

async def display_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = context._user_id
    print(f"User {user} is displaying grocery list...")
    response = GM.handle_display_command(user)
    await update.message.reply_text(response)

# ERRORS
async def error(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"Update {update} cause error {context.error}")

# MESSAGE HANDLING

def isUserRude(user_msg: str) -> bool:
    for word in user_msg.split():
        if word == word.upper():
            return True
    return False

def handle_response(user_msg: str, user: int) -> str:
    isNormalEcho = True
    # Check managers for active, else do default echo
    for manager in managers:
        if not manager.isActive or user != manager.expectedUser:
            continue

        response = manager.handle_message(user_msg)
        isNormalEcho = False

    if not isNormalEcho:
        return response

    # =====================
    # Normal echo behaviour
    global isAngry
    isAngry = isAngry or isUserRude(user_msg)
    if not isAngry:
        return user_msg
    else:
        return user_msg.upper()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    message_type: str = update.message.chat.type # group or private
    text: str = update.message.text
    user: int = context._user_id

    print(f"User {user} said {text}")

    # Only reply in group if tagged
    if message_type.lower() == "group" or "supergroup":
        if BOT_NAME in text:
            response: str = handle_response(text.replace(BOT_NAME,""), user)
        else:
            return
    elif message_type.lower() == "private":
        response: str = handle_response(text, user)
    else:
        print("Unknown type of chat incoming. Ignoring")

    await update.message.reply_text(response)




def main() -> None:
    with open(TOKEN_FILE, "r") as f:
        TOKEN = f.readline().strip()

    print("Bot starting...")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("sorry", sorry_command))
    app.add_handler(CommandHandler("need", need_command))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(CommandHandler("remove", remove_command, has_args=True))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("display", display_command))
    # TODO: Fix done/display commands, error Message text is empty (i think the bot trying to relp with nothing)
    app.add_handler(MessageHandler(filters.TEXT, handle_message))

    app.add_error_handler(error)

    print("Polling...")
    app.run_polling(poll_interval=3)

    # On app shutdown
    GM.save()


if __name__ == '__main__':
    main()