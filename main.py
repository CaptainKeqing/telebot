import logging

from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, Application, ContextTypes, InlineQueryHandler

from grocery_manager import GroceryManager

logger = logging.getLogger(__name__)
TOKEN_FILE = "bot_token.txt"
BOT_NAME = "@ddonobot"

def get_available_ram_linux_gb():
    """
    Retrieves available RAM in GB on Linux by parsing /proc/meminfo.
    """
    with open('/proc/meminfo') as file:
        for line in file:
            if 'MemAvailable:' in line:
                # The value is in the second column
                return int(line.split()[1]) / (1024**2)
    return 0
ESTIMATE_RAM_PER_DRIVER_GB = 0.6  # Estimated RAM usage per Selenium driver in GB
available_ram = get_available_ram_linux_gb()
num_drivers = max(1, int(available_ram / ESTIMATE_RAM_PER_DRIVER_GB))
num_drivers = min(2, num_drivers)  # Cap at 5 drivers

print(f"Available RAM: {available_ram:.2f} GB, setting up to {num_drivers} workers.")
GM = GroceryManager(num_drivers)
# COMMANDS
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Hello! I'm donobot.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("How to use me:\n\n" \
    "I'm an inline bot that helps you with all your grocery needs. Just" \
    " type @ddonobot in any chat, followed by your search term.\n\n" \
    "Select the item you want to add to your grocery list, and that's all!.\n\n" \
    "Every chat has a shared grocery list.\n\n"
    "To display your current list, use /display\n\n"
    "To remove groceries, do /remove <indexes separated by space>\n"
    )

# ERRORS
async def error(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"Update {update} cause error {context.error.with_traceback(None)}")


async def post_init_callback(application: Application) -> None:
    try:
        await GM.initialise()
    except Exception as e:
        print(f"Error during GM initialisation: {e}")



def main() -> None:
    with open(TOKEN_FILE, "r") as f:
        TOKEN = f.readline().strip()

    print("GM initialising...")
    print("Bot starting...")
    app = Application.builder().token(TOKEN).post_init(post_init_callback).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))

    # GM commands
    app.add_handler(CommandHandler("remove", GM.remove_command))
    app.add_handler(CommandHandler("clear", GM.clear_command))
    app.add_handler(CommandHandler("display", GM.display_command))

    app.add_handler(MessageHandler(filters.VIA_BOT, GM.handle_via_bot_message))


    # Inline query handler
    app.add_handler(InlineQueryHandler(GM.inline_query_handler))
    app.add_error_handler(error)

    print("Polling...")
    app.run_polling(poll_interval=0.1)

    # On app shutdown
    print("GM saving...")
    GM.save()


if __name__ == '__main__':
    main()