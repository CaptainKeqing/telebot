import shelve
import random

import asyncio

from telegram import Update, InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import ContextTypes

from fairprice_quierer import FPQLoadBalancer


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
    def __init__(self, num_drivers):
        self.inlineMessageSignature = "\u0020\u2004\u2005\u0020\u00A0"
        self.inlineMessageSignatureORD = [ord(c) for c in self.inlineMessageSignature]
        self.SAVE_DB = "GM.db"
        self.db: shelve.Shelf = shelve.open(self.SAVE_DB)

        # To support multiple chats, we need a mapping from chat_id to GroceryList and variables
        # Each chat will share a GroceryList instance
        self.grocery_lists: dict[str, GroceryList] = {}
        
        self.acknowledgements = ["Okay!", "Got it.", "Writing that down...", "Ack."]

        self.FPQ = FPQLoadBalancer(num_drivers)

    async def initialise(self):
        await self.FPQ.initialise()
    def is_message_signed(self, text: str) -> bool:
        found = True
        # Assume signature is tagged on the back
        for i in range(len(self.inlineMessageSignatureORD)):
            if self.inlineMessageSignatureORD[i] != ord(text[-len(self.inlineMessageSignatureORD) + i]):
                found = False
                break
        return found
    
    def sign_message(self, text: str) -> str:
        return text + self.inlineMessageSignature

    async def inline_query_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        inline_query: InlineQuery = update.inline_query
        query_text = inline_query.query.strip()
        
        # Don't handle empty query
        if not query_text:
            return
        
        # Query products from FairPrice
        loop = asyncio.get_running_loop()

        products = await loop.run_in_executor(
            self.FPQ.executor,
            self.FPQ.get,
            query_text
        )
        
        if not products:
            print("No products found for inline query.")
            await inline_query.answer([])
            return
        
        # Build inline query results with product info
        iqrs = []
        for idx, product in enumerate(products):
            # print("Product found:", product)
            message_text = self.sign_message(f"{product.item_name} - {product.item_price}")
            iqr = InlineQueryResultArticle(
                id=f"product_{idx}",
                thumbnail_url=product.image_url,
                title=product.item_name,
                description=product.item_price,
                input_message_content=InputTextMessageContent(
                    message_text=message_text
                ),
            )
            iqrs.append(iqr)
        
        await inline_query.answer(iqrs)

    def add_to_grocery_list(self, chat_id: str, item: str) -> None:
        glist = self.get_grocery_list(chat_id)
        glist.add(item.strip()) # Get rid of signature if any

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

    async def handle_via_bot_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message is None:
            return
        text: str = update.message.text
        user_id: int = update.effective_user.id
        chat_id = str(update.effective_chat.id)
        # It is impossible to tell if the message is VIA the bot itself, or VIA another bot
        # But we use the GM inlineMessageSignature with a zero-width space to identify messages from ourselves

        if self.is_message_signed(text):
            self.add_to_grocery_list(chat_id, text)
            ack = random.choice(self.acknowledgements)
            await update.message.reply_text(ack)
            return
        else:
            print("No signature found, ignoring")
            return

    async def remove_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id: int = update.effective_user.id
        chat_id = str(update.effective_chat.id)
        args = context.args
        print(f"User {user_id} invoking remove command")

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

    # # Good to have functions
    # def get_cost(self, item: str) -> list[FairpriceItem]:
    #     """Webscraping to get cost"""
    #     return self.fpq.query(item)

    def get_closest_supermarkets(self, location):
        pass