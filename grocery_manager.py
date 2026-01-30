import os
import pickle
import random

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update, Bot
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from fairprice_quierer import FairpriceQuerier, FairpriceItem

class GroceryList:
    def __init__(self):
        self._list = []

    def add(self, item: str) -> None:
        self._list.append(item)

    def remove(self, ind: int) -> bool:
        zero_based_ind = ind - 1
        if zero_based_ind < 0 or zero_based_ind >= len(self._list):
            return False
        self._list.pop(ind-1)
        return True

    def display(self) -> str:
        response = ""
        for ind, item in enumerate(self._list):
            response += f"{ind+1}) {item}\n"
        return response
    
    def clear(self) -> None:
        self._list.clear()

class GroceryManager:
    def __init__(self):
        self.SAVE_FILE = "GM.pickle"
        if os.path.exists(self.SAVE_FILE):
            with open(self.SAVE_FILE, "rb") as f:
                self._glist: GroceryList = pickle.load(f)
        else:
            self._glist: GroceryList = GroceryList()
        self.isActive: bool = False
        self.expectedUser: int = -1

        self.acknowledgements = ["Okay!", "Got it.", "Writing that down...", "Ack"]

        self.fpq = FairpriceQuerier()
        self.product_options = []
        self.selected_product = 0

        self.button_left = InlineKeyboardButton("L", callback_data="L")
        self.button_right = InlineKeyboardButton("R", callback_data="R")
        self.button_select = InlineKeyboardButton("Y", callback_data="Y")
        self.inline_keyboard = InlineKeyboardMarkup([[self.button_left, self.button_select, self.button_right]])
    
    def save(self):
        with open(self.SAVE_FILE, "wb") as f:
            pickle.dump(self._glist, f, pickle.HIGHEST_PROTOCOL) # Save the whole GroceryList, might add more fields in future

    async def handle_message(self, user_msg: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        print("GM handling message")
        item = user_msg.strip()

        await update.message.reply_text("Give me a while to check...")
        self.product_options = self.fpq.query(item)
        self.selected_product = 0
        if len(self.product_options) == 0:
            await update.message.reply_text("Sorry, no items found.")
            return

        # print("Sanity Check")
        # for i in range(min(5, len(self.product_options))):
        #     print(self.product_options[i].item_name, self.product_options[i].item_price)

        caption = f'{self.product_options[self.selected_product].item_name} {self.product_options[self.selected_product].item_price}'
        await update.message.reply_photo(self.product_options[self.selected_product].image_url, caption=caption, reply_markup=self.inline_keyboard)

    async def onInlineButtonPress(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query.data == "L":
            self.selected_product = (self.selected_product - 1) % len(self.product_options)
        elif query.data == "R":
            self.selected_product = (self.selected_product + 1) % len(self.product_options)
        elif query.data == "Y":
            product = f"{self.product_options[self.selected_product].item_name} {self.product_options[self.selected_product].item_price}"
            self._glist.add(product)
            await query.message.chat.send_message(self.acknowledgements[random.randint(0, len(self.acknowledgements)-1)])
            if query.message.is_accessible:
                await query.message.delete()
            return

        try:
            caption = f'{self.product_options[self.selected_product].item_name} {self.product_options[self.selected_product].item_price}'
            media = InputMediaPhoto(self.product_options[self.selected_product].image_url, caption=caption)
            await query.edit_message_media(media, reply_markup=self.inline_keyboard)
        except TelegramError as e:
            print("error in callback query", e)
            await query.get_bot().answer_callback_query(query.id, "Error")
            raise e

    def get_expected_user(self) -> int:
        return self.expectedUser

    # GroceryManager commands
    async def need_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = context._user_id
        print(f"User {user} invoking need command")
        if self.isActive:
            print("Trying to start 2 consecutive buy operations... Not entertaining")
            await update.message.reply_text("Sorry! I cannot serve 2 people at once! Please wait till the other user has" \
            " finished adding to the list.")
            return
        self.isActive = True
        self.expectedUser = user
        await update.message.reply_text("What do you need to buy?")

    async def done_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = context._user_id

        print(f"User {user} invoking done command")
        if not self.isActive:
            await update.message.reply_text("Can't be done with what you haven't started!")
            return

        if user != self.expectedUser:
            print("Other user trying to stop buy operation. Ignoring...")
            await update.message.reply_text("Don't be rude, let him finish.")
            return

        self.isActive = False
        self.expectedUser = -1
        response = "Okay, here's your compiled grocery list.\n" + self._glist.display()
        await update.message.reply_text(response)

    async def remove_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = context._user_id
        args = context.args
        print(f"User {user} invoking remove command")
        if self.isActive and user != self.expectedUser:
            await update.message.reply_text("Another user is currently adding items. Please wait until he/she is finished.")
        descending_inds = []
        for ind in args:
            if ind.isdigit():
                descending_inds.append(int(ind))

        descending_inds.sort(reverse=True)

        if len(descending_inds) == 0:
            await update.message.reply_text("Please specify an index to remove")
            return

        for ind in descending_inds:
            print(f"Removing {ind} from list")
            self._glist.remove(ind)
        
        response = "Okay, here's your compiled grocery list.\n" + self._glist.display()
        await update.message.reply_text(response)

    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = context._user_id
        print(f"User {user} invoking clear command")
        if self.isActive:
            await update.message.reply_text("Can't clear list while user is actively adding items.")
            return
        self._glist.clear()
        await update.message.reply_text("Grocery list has been cleared.")

    async def display_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = context._user_id
        print(f"User {user} invoking display command")
        response = "Okay, here's your compiled grocery list.\n" + self._glist.display()
        await update.message.reply_text(response)

    # Good to have functions
    def get_cost(self, item: str) -> list[FairpriceItem]:
        """Webscraping to get cost"""
        return self.fpq.query(item)

    def get_closest_supermarkets(self, location):
        pass