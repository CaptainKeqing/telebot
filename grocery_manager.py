import pprint
import random

from telegram import Update
from telegram.ext import ContextTypes

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


class GroceryManager:
    def __init__(self):
        self._glist: GroceryList = GroceryList()
        self.isActive: bool = False
        self.expectedUser: int = -1

        self.acknowledgements = ["Okay!", "Got it.", "Writing that down...", "Ack"]

    def handle_message(self, user_msg: str) -> str:
        print("GM handling message")
        item = user_msg.strip()
        self._glist.add(item)

        return self.acknowledgements[random.randint(0, len(self.acknowledgements)-1)] 

    def get_expected_user(self) -> int:
        return self.expectedUser

    def handle_need_command(self, user: int) -> str:
        print(f"User {user} invoking need command")
        if self.isActive:
            print("Trying to start 2 consecutive buy operations... Not entertaining")
            return "Sorry! I cannot serve 2 people at once! Please wait till the other user has" \
            "finished adding to the list."
        self.isActive = True
        self.expectedUser = user
        return "What do you need to buy?"

    def handle_done_command(self, user: int) -> str:
        print(f"User {user} invoking done command")
        if not self.isActive:
            return "Can't be done with what you haven't started!"

        if user != self.expectedUser:
            print("Other user trying to stop buy operation. Ignoring...")
            return "Don't be rude, let him finish."

        self.isActive = False
        self.expectedUser = -1
        response = "Okay, here's your compiled grocery list.\n" + self._glist.display()
        return response

    def handle_remove_command(self, user: int, args: list[str]) -> str:
        print(f"User {user} invoking remove command")
        if self.isActive:
            if user != self.expectedUser:
                return "Another user is currently adding items. Please wait until he/she is finished."
        descending_inds = []
        for ind in args:
            if ind.isdigit():
                descending_inds.append(int(ind))

        descending_inds.sort(reverse=True)

        for ind in descending_inds:
            print(f"Removing {ind+1} from list")
            self._glist.remove(ind)
                

    def handle_clear_command(self, user: int) -> str:
        print(f"User {user} invoking clear command")
        if self.isActive:
            return "Can't clear list while user is actively adding items."
        return "Grocery list has been cleared."

    # Good to have functions
    def get_cost(self, item: str):
        """Webscraping to get cost"""
        pass

    def get_closest_supermarkets(self, location):
        pass