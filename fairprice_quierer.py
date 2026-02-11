from typing import NamedTuple
from queue import Queue
import threading
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver import Keys


class FairpriceItem(NamedTuple):
    image_url: str
    item_name: str
    item_price: str

class FairpriceQuerier:

    def __init__(self):
        self.WEBSITE = "https://www.fairprice.com.sg"
        self.NET_PRICE_XPATH = "//span[@class='sc-ab6170a9-1 sc-65bf849-1 gDJNWQ cXCGWM']"
        self.PRODUCT_IMAGE_XPATH = '//img[@class="sc-aca6d870-0 janHcI"]' # Also contains product name

        self.driver = webdriver.Chrome()
        self.driver.get(self.WEBSITE)
        self.previous_search = ""

    def get_driver(self):
        try:
            if self.driver.title:  # Simple operation to check if driver is alive
                return self.driver
        except:
            print("Oh no driver dead")
            self.driver.quit()
            self.driver = webdriver.Chrome()
            self.driver.get(self.WEBSITE)
            self.previous_search = ""
            return self.driver
        
    def query(self, search_term: str) -> list[FairpriceItem]:
        self.get_driver()  # Ensure driver is alive
        if search_term != self.previous_search:
            self.previous_search = search_term
            search_bar = self.driver.find_element(By.ID, "search-input-bar")
            # Effectively clears search_bar. .clear() does not work
            search_bar.send_keys(Keys.CONTROL + "a")
            search_bar.send_keys(Keys.BACK_SPACE)

            search_bar.send_keys(search_term)
            search_bar.send_keys(Keys.ENTER)
            try:
                WebDriverWait(self.driver, 5, poll_frequency=0.5).until(EC.title_contains(search_term))
            except:
                print("No results found")
                return []
        
        viewport_height = self.driver.execute_script("return window.innerHeight;")

        ActionChains(self.driver).scroll_by_amount(0, viewport_height).perform()
        image_elements = self.driver.find_elements(By.XPATH, self.PRODUCT_IMAGE_XPATH)
        net_price_elements = self.driver.find_elements(By.XPATH, self.NET_PRICE_XPATH)

        images = list(map(lambda elem: elem.get_attribute("src"), image_elements))
        item_names = list(map(lambda elem: elem.get_attribute("alt"), image_elements))
        net_prices = list(map(lambda elem: elem.text, net_price_elements))

        resp = []
        for i in range(min(10, len(images))):  # Extract only the top 10
            resp.append(FairpriceItem(images[i], item_names[i], net_prices[i]))
        
        return resp

class FPQLoadBalancer: 
    def __init__(self, num_instances: int = 2):
        self.pool: Queue[FairpriceQuerier] = Queue()
        for _ in range(num_instances):
            self.pool.put(FairpriceQuerier())
        
        # Start background thread for periodic pinging
        self.ping_thread = threading.Thread(target=self._ping_worker, daemon=True)
        self.ping_thread.start()

    def query(self, search_term: str) -> list[FairpriceItem]:
        FPQ = self.pool.get()  # Blocks until a driver is available
        try:
            result = FPQ.query(search_term)
            return result
        finally:
            self.pool.put(FPQ)

    # Do periodic pinging to keep the drivers alive, revive if necessary
    def ping_all(self) -> None:
        for _ in range(self.pool.qsize()):
            FPQ = self.pool.get()
            try:
                driver = FPQ.get_driver()
            finally:
                print("Releasing driver back to pool...")
                self.pool.put(FPQ)

    def _ping_worker(self) -> None:
        """Background worker that pings all drivers every 5 minutes."""
        while True:
            print("Pinging all FairpriceQuerier instances to keep them alive...")
            time.sleep(300)  # 5 minutes
            self.ping_all()
