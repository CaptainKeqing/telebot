import os
import pickle
import random

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update, CallbackQuery, Chat
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

        # To prevent multiple messages from same user being queried at once
        self.isEngagingExpectedUser: bool = False

        self.acknowledgements = ["Okay!", "Got it.", "Writing that down...", "Ack"]

        self.fpq = FairpriceQuerier()
        self.product_options = []
        self.po_start_window = 0
        self.window_size = 5

        self.sent_media_group = []

        self.button_left = InlineKeyboardButton("⬅️", callback_data="L")
        self.button_right = InlineKeyboardButton("➡️", callback_data="R")
        self.button_cancel = InlineKeyboardButton("❌️", callback_data="cancel")
        self.select_1 = InlineKeyboardButton("1️⃣", callback_data="1")
        self.select_2 = InlineKeyboardButton("2️⃣", callback_data="2")
        self.select_3 = InlineKeyboardButton("3️⃣", callback_data="3")
        self.select_4 = InlineKeyboardButton("4️⃣", callback_data="4")
        self.select_5 = InlineKeyboardButton("5️⃣", callback_data="5")
        self.select_button_list = [self.select_1, self.select_2, self.select_3, self.select_4, self.select_5]
        self.navigation_button_list = [self.button_left, self.button_cancel, self.button_right]
        # self.inline_keyboard = InlineKeyboardMarkup([[self.select_left, self.select_select, self.select_right]])
    
    def save(self):
        with open(self.SAVE_FILE, "wb") as f:
            pickle.dump(self._glist, f, pickle.HIGHEST_PROTOCOL) # Save the whole GroceryList, might add more fields in future

    async def delete_grocery_prompts(self, query: CallbackQuery):
        await query.message.chat.delete_messages([m.id for m in self.sent_media_group])
        if query.message.is_accessible:
            await query.message.delete()

    def get_formal_name(self, index: int):
        """
        Get product name + price. 

        Zero based index of self.product_options
        """
        return f"{self.product_options[index].item_name} {self.product_options[index].item_price}"

    async def send_media_group(self, chat: Chat):
        """
        Prompt user with media group and inline keyboard.
        
        Updates self.sent_media_group.

        Zero based index window of self.product_options
        """
        print("Product options length", len(self.product_options))
        po_end_window = self.po_start_window + min(self.window_size, len(self.product_options))
        #print product urls in window
        for p in self.product_options[self.po_start_window:po_end_window]:
            print(p.image_url)
        image_urls = [InputMediaPhoto(p.image_url) for p in self.product_options[self.po_start_window:po_end_window]]
        self.sent_media_group = await chat.send_media_group(image_urls, read_timeout=30)
        
        caption = "Here are some products:\n"
        for id in range(len(self.sent_media_group)):
            caption += f"{id+1}) {self.get_formal_name(id+self.po_start_window)}\n"


        # print("Full options:\n")
        # map(lambda p: print(p.item_name), self.product_options)

        inline_keyboard = InlineKeyboardMarkup([self.select_button_list[:len(self.sent_media_group)], self.navigation_button_list])
        await chat.send_message(caption, reply_markup=inline_keyboard, read_timeout=30)

    async def handle_message(self, user_msg: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        print("GM handling message")
        if self.isEngagingExpectedUser == True:
            print("Already engaging expected user. Ignoring message")
            return
        item = user_msg.strip()

        await update.message.reply_text("Give me a while to check...")
        self.isEngagingExpectedUser = True
        self.product_options = self.fpq.query(item)
        self.po_start_window = 0
        if len(self.product_options) == 0:
            await update.message.reply_text("Sorry, no items found.")
            self.isEngagingExpectedUser = False
            return


        await self.send_media_group(update.effective_chat)
 

    async def onInlineButtonPress(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query.data == "L":
            if len(self.product_options) <= self.window_size:
                await query.answer("No more!")
            self.po_start_window -= self.window_size
            if self.po_start_window < 0:
                self.po_start_window = len(self.product_options) - self.window_size
                assert self.po_start_window >= 0
        elif query.data == "R":
            if len(self.product_options) <= self.window_size:
                await query.answer("No more!")
            self.po_start_window += self.window_size
            if self.po_start_window >= len(self.product_options):
                self.po_start_window = 0
        elif query.data == "cancel":
            await query.answer("Cancelling query.")
            await self.delete_grocery_prompts(query)
            return

        elif query.data in "12345":
            id = int(query.data) - 1 + self.po_start_window
            self._glist.add(self.get_formal_name(id))

            await query.message.chat.send_message(self.acknowledgements[random.randint(0, len(self.acknowledgements)-1)])
            await self.delete_grocery_prompts(query)
            self.isEngagingExpectedUser = False
            return

        await self.delete_grocery_prompts(query)

        await self.send_media_group(update.effective_chat)

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