import shelve
import random

from enum import Enum

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update, CallbackQuery, Message
from telegram.ext import ContextTypes

from fairprice_quierer import FairpriceQuerier, FairpriceItem


class UserState(Enum):
    IN_NEED = 0  # After invoking /need, but not yet querying
    ACTIVE = 1  # After at least 1 instance of querying, before /done
    IDLE = 2    # Not in need


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
        self.SAVE_DB = "GM.db"
        self.db: shelve.Shelf = shelve.open(self.SAVE_DB)

        # To support multiple chats, we need a mapping from chat_id to GroceryList and variables
        # Each chat will share a GroceryList instance
        self.grocery_lists: dict[str, GroceryList] = {}
        
        # To prevent multiple messages from same user being queried at once during need
        self.userStatesInChat: dict[str, dict[int, UserState]] = {}  # chat_id -> user_id -> UserState

        self.product_options: dict[str, dict[int, list[FairpriceItem]]] = {}  # chat_id -> user_id -> list of FairpriceItem
        self.po_start_windows: dict[str, dict[int, int]] = {}  # chat_id -> user_id -> list of start windows
        self.window_size = 3  # For now, make it fixed at 3

        # We separate the InputMediaPhoto list from FairpriceItem list for separation of concerns
        self.product_options_medias: dict[str, dict[int, list[InputMediaPhoto]]] = {}  # chat_id -> user_id -> list of InputMediaPhoto
        self.sent_media_groups: dict[str, dict[int, tuple[Message]]] = {}  # chat_id -> user_id -> tuple of telegram.Message

        self.acknowledgements = ["Okay!", "Got it.", "Writing that down...", "Ack."]

        self.fpq = FairpriceQuerier()

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

        assert self.window_size <= 5, "Window size cannot be greater than 5 due to button limitations."

    def get_grocery_list(self, chat_id: str) -> GroceryList:
        if chat_id not in self.grocery_lists:
            # Check database
            if chat_id in self.db:
                self.grocery_lists[chat_id] = self.db[chat_id]
            else:
                self.grocery_lists[chat_id] = GroceryList()
        return self.grocery_lists[chat_id]

    def save(self):
        for chat_id, glist in self.grocery_lists.items():
            self.db[chat_id] = glist
        self.db.close()

    async def delete_grocery_prompts(self, query: CallbackQuery):
        chat_id = str(query.message.chat.id)
        user_id: int = query.from_user.id

        print("Delete GP")
        print("Chat ID:", chat_id, "User ID:", user_id)

        assert chat_id in self.sent_media_groups, "delete_grocery_prompts called before any querying in chat"
        assert user_id in self.sent_media_groups[chat_id], "delete_grocery_prompts called before any querying by user in chat"

        await query.message.chat.delete_messages([m.id for m in self.sent_media_groups[chat_id][user_id]])
        if query.message.is_accessible:
            await query.message.delete()

    def get_formal_name(self, chat_id: str, user_id: int, index: int):
        """
        Get product name + price. 

        Zero based index of product_options list
        """
        assert chat_id in self.product_options, "onInlineButtonPress called before any querying in chat"
        assert user_id in self.product_options[chat_id], "onInlineButtonPress called before any querying by user in chat"

        po = self.product_options[chat_id][user_id]
        return f"{po[index].item_name} {po[index].item_price}"


    async def send_media_group(self, update: Update):
        """
        Prompt user with media group and inline keyboard.
        
        Updates self.sent_media_groups.

        Zero based index window of product_options
        """
        user_id: int = update.effective_user.id
        chat_id = str(update.effective_chat.id)
        print("Reply MG")
        print("Chat ID:", chat_id, "User ID:", user_id)
        po_media = self.product_options_medias[chat_id][user_id]
        po_start_window = self.po_start_windows[chat_id][user_id]

        po_end_window = min(po_start_window + self.window_size,
                             len(po_media))

        sent_media_group = await update.effective_chat.send_media_group(po_media[po_start_window:po_end_window], read_timeout=20)
        
        caption = "Here are some products:\n"
        for id in range(len(sent_media_group)):
            caption += f"{id+1}) {self.get_formal_name(chat_id, user_id, id+po_start_window)}\n"

        inline_keyboard = InlineKeyboardMarkup([self.select_button_list[:len(sent_media_group)], self.navigation_button_list])
        await update.effective_chat.send_message(caption, reply_markup=inline_keyboard, read_timeout=20)

        if chat_id not in self.sent_media_groups:
            self.sent_media_groups[chat_id] = {}
        self.sent_media_groups[chat_id][user_id] = sent_media_group

    async def execute_query(self, item: str, update: Update) -> bool:
        """Executes query with FPQ and populates product_options"""
        chat_id = str(update.effective_chat.id)
        user_id: int = update.effective_user.id
        print("Execute query")
        print("Chat ID:", chat_id, "User ID:", user_id)
        if chat_id not in self.product_options:
            self.product_options[chat_id] = {}
            self.product_options_medias[chat_id] = {}
            self.po_start_windows[chat_id] = {}

        self.product_options[chat_id][user_id] = self.fpq.query(item)
        self.product_options_medias[chat_id][user_id] = [InputMediaPhoto(p.image_url) for p in self.product_options[chat_id][user_id]]
        self.po_start_windows[chat_id][user_id] = 0

        if len(self.product_options[chat_id][user_id]) == 0:
            await update.message.reply_text("Sorry, no items found.")
            return False
        return True

    async def handle_message(self, user_msg: str, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        print("GM handling message")
        chat_id = str(update.effective_chat.id)
        user_id: int = update.effective_user.id
        
        if chat_id not in self.userStatesInChat:
            self.userStatesInChat[chat_id] = {}

        if user_id not in self.userStatesInChat[chat_id]:
            self.userStatesInChat[chat_id][user_id] = UserState.IDLE

        if self.userStatesInChat[chat_id][user_id] == UserState.ACTIVE:
            print("User is already querying FPQ. Ignoring message")
            return

        item = user_msg.strip()

        await update.message.reply_text("Give me a while to check...")

        query_success = await self.execute_query(item, update)
        if not query_success:
            await update.message.reply_text("What else do you need?")
            self.userStatesInChat[chat_id][user_id] = UserState.IN_NEED
            return

        self.userStatesInChat[chat_id][user_id] = UserState.ACTIVE
        await self.send_media_group(update)
 

    async def onInlineButtonPress(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        chat_id = str(update.effective_chat.id)
        user_id: int = update.effective_user.id
        
        assert chat_id in self.product_options, "onInlineButtonPress called before any querying in chat"
        assert user_id in self.product_options[chat_id], "onInlineButtonPress called before any querying by user in chat"
        # TODO: I already know there is a bug here if multiple users in same chat are querying,
        # and a user presses another user's inline button. Fix later.
        po = self.product_options[chat_id][user_id]

        if query.data == "L":
            if len(po) <= self.window_size:
                await query.answer("No more!")
            self.po_start_windows[chat_id][user_id] -= self.window_size
            if self.po_start_windows[chat_id][user_id] < 0:
                self.po_start_windows[chat_id][user_id] = len(po) - self.window_size
                assert self.po_start_windows[chat_id][user_id] >= 0

        elif query.data == "R":
            if len(po) <= self.window_size:
                await query.answer("No more!")
            self.po_start_windows[chat_id][user_id] += self.window_size
            if self.po_start_windows[chat_id][user_id] >= len(po):
                self.po_start_windows[chat_id][user_id] = 0

        elif query.data == "cancel":
            await query.answer("Cancelling query.")
            await self.delete_grocery_prompts(query)
            self.userStatesInChat[chat_id][user_id] = UserState.IN_NEED
            return

        elif query.data in "12345":
            id = int(query.data) - 1 + self.po_start_windows[chat_id][user_id]

            glist = self.get_grocery_list(chat_id)
            product_to_add = self.get_formal_name(chat_id, user_id, id)
            glist.add(product_to_add)

            acknowledgement_text = (self.acknowledgements[random.randint(0, len(self.acknowledgements)-1)] 
                                    + f" Added {product_to_add} to your grocery list.")

            await query.message.chat.send_message(acknowledgement_text)
            await self.delete_grocery_prompts(query)
            self.userStatesInChat[chat_id][user_id] = UserState.IN_NEED
            return

        await self.delete_grocery_prompts(query)

        await self.send_media_group(update)

    # GroceryManager commands
    async def need_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id: int = update.effective_user.id
        chat_id = str(update.effective_chat.id)
        print(f"User {user_id} invoking need command")

        if chat_id not in self.userStatesInChat:
            self.userStatesInChat[chat_id] = {}

        if user_id not in self.userStatesInChat[chat_id]:
            self.userStatesInChat[chat_id][user_id] = UserState.IDLE

        if self.userStatesInChat[chat_id][user_id] == UserState.IN_NEED or self.userStatesInChat[chat_id][user_id] == UserState.ACTIVE:
            print("User already adding items. Ignoring...")
            await update.message.reply_text("You are already adding items to the grocery list. Please finish that first.")
            return

        # self.activeUsersInChat.setdefault(chat_id, set()).add(user_id)
        self.userStatesInChat[chat_id][user_id] = UserState.IN_NEED
        await update.message.reply_text(f"Hi {update.effective_user.name}. What do you need to buy?")

    async def done_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id: int = update.effective_user.id
        chat_id = str(update.effective_chat.id)
        print(f"User {user_id} invoking done command")

        if chat_id not in self.userStatesInChat:
            self.userStatesInChat[chat_id] = {}

        if user_id not in self.userStatesInChat[chat_id]:
            self.userStatesInChat[chat_id][user_id] = UserState.IDLE

        if self.userStatesInChat[chat_id][user_id] == UserState.IDLE:
            await update.message.reply_text("Can't be done with what you haven't started!")
            return

        grocery_list = self.get_grocery_list(chat_id)

        self.userStatesInChat[chat_id][user_id] = UserState.IDLE
        response = "Okay, here's your compiled grocery list.\n" + grocery_list.display()
        await update.message.reply_text(response)

    async def remove_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id: int = update.effective_user.id
        chat_id = str(update.effective_chat.id)
        args = context.args
        print(f"User {user_id} invoking remove command")

        if chat_id not in self.userStatesInChat:
            self.userStatesInChat[chat_id] = {}

        if user_id not in self.userStatesInChat[chat_id]:
            self.userStatesInChat[chat_id][user_id] = UserState.IDLE

        # For remove, we do not allow if ANY user is active. Race condition. Does not matter if user is IN_NEED
        if any(map(lambda state: state == UserState.ACTIVE,
                    self.userStatesInChat[chat_id].values())):
            await update.message.reply_text("Hold on, someone is in the middle of adding items. Let's finish that first.")
            return

        descending_inds = []
        for ind in args:
            if ind.isdigit():
                descending_inds.append(int(ind))

        descending_inds.sort(reverse=True)

        if len(descending_inds) == 0:
            await update.message.reply_text("Proper usage: /remove <item numbers separated by space>" \
            ". For example: /remove 2 5 7")
            return

        out_of_bounds_inds = []
        grocery_list = self.get_grocery_list(chat_id)
        for ind in descending_inds:
            if not grocery_list.remove(ind):
                out_of_bounds_inds.append(ind)
            else:
                print(f"Removing {ind} from list")
        response = "Here's your compiled grocery list.\n" + grocery_list.display()
        await update.message.reply_text(response)

        # If any out of bounds indices, inform user
        if len(out_of_bounds_inds) > 0:
            await update.message.reply_text("The following item numbers were out of bounds and could not be removed: " +
            ", ".join([str(i) for i in out_of_bounds_inds]))


    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id: int = update.effective_user.id
        chat_id = str(update.effective_chat.id)
        print(f"User {user_id} invoking clear command")

        if chat_id not in self.userStatesInChat:
            self.userStatesInChat[chat_id] = {}

        if user_id not in self.userStatesInChat[chat_id]:
            self.userStatesInChat[chat_id][user_id] = UserState.IDLE

        # For clear, we do not allow if ANY user is querying. Race condition.
        if any(map(lambda state: state == UserState.ACTIVE,
                    self.userStatesInChat[chat_id].values())):
            await update.message.reply_text("Hold on, someone is in the middle of adding items. Let's finish that first.")
            return

        grocery_list = self.get_grocery_list(chat_id)
        grocery_list.clear()
        await update.message.reply_text("Grocery list has been cleared.")

    async def display_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id: int = update.effective_user.id
        chat_id = str(update.effective_chat.id)
        print(f"User {user_id} invoking display command")
        grocery_list = self.get_grocery_list(chat_id)
        response = "Okay, here's your compiled grocery list.\n" + grocery_list.display()
        await update.message.reply_text(response)

    # Good to have functions
    def get_cost(self, item: str) -> list[FairpriceItem]:
        """Webscraping to get cost"""
        return self.fpq.query(item)

    def get_closest_supermarkets(self, location):
        pass