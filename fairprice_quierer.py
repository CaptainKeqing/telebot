import asyncio
import threading
import time

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from queue import Queue
from typing import NamedTuple

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver import Keys
from selenium.common.exceptions import NoSuchElementException


class FairpriceItem(NamedTuple):
    image_url: str
    item_name: str
    item_price: str

class FairpriceQuerier:

    def __init__(self):
        self.WEBSITE = "https://www.fairprice.com.sg"
        self.NET_PRICE_XPATH = "//span[@class='sc-ab6170a9-1 sc-65bf849-1 gDJNWQ cXCGWM']"
        self.PRODUCT_IMAGE_XPATH = '//img[@class="sc-aca6d870-0 janHcI"]' # Also contains product name

        self.init_driver()

    def init_driver(self):
        options = webdriver.ChromeOptions()
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-sync")
        options.add_argument("--metrics-recording-only")
        options.add_argument("--disable-default-apps")
        options.add_argument("--mute-audio")
        options.add_argument('--headless=new')
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        self.driver = webdriver.Chrome(options)
        self.driver.get(self.WEBSITE)
        self.previous_search = ""

    def get_driver(self):
        try:
            if self.driver.title:  # Simple operation to check if driver is alive
                return self.driver
        except:
            print("Oh no driver dead")
            # self.driver.quit()
            self.init_driver()
            return self.driver
        
    def query(self, search_term: str) -> list[FairpriceItem]:
        self.get_driver()  # Ensure driver is alive
        if search_term != self.previous_search:
            self.previous_search = search_term
            try:
                search_bar = self.driver.find_element(By.ID, "search-input-bar")
                # Effectively clears search_bar. .clear() does not work
                search_bar.send_keys(Keys.CONTROL + "a")
                search_bar.send_keys(Keys.BACK_SPACE)

                search_bar.send_keys(search_term)
                search_bar.send_keys(Keys.ENTER)
            except NoSuchElementException:
                print("Search bar not found")
                return []
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



@dataclass(slots=True)
class CacheEntry:
    timestamp: float
    value: list
    refreshing: bool = False


class SWRLRUCache:
    def __init__(self, max_size=10_000, ttl=3600, common_ttl=86400):
        self._max_size = max_size
        self._ttl = ttl
        self._common_ttl = common_ttl

        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self._common_terms: set[str] = set()

    def set_common(self, terms: set[str]):
        self._common_terms = terms

    def get(self, key: str) -> tuple[list[FairpriceItem] | None, bool]:
        now = time.time()

        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None, False

            ttl = self._common_ttl if key in self._common_terms else self._ttl
            age = now - entry.timestamp

            # Expired completely (hard expire)
            if age > ttl * 2:
                del self._cache[key]
                return None, False

            # Soft expired → return stale + refresh
            if age > ttl:
                if not entry.refreshing:
                    entry.refreshing = True
                    refresh_needed = True
                else:
                    refresh_needed = False

                self._cache.move_to_end(key)
                return entry.value, refresh_needed

            # Fresh
            self._cache.move_to_end(key)
            return entry.value, False

    def set(self, key: str, value: list):
        if not value:
            return

        with self._lock:
            self._cache[key] = CacheEntry(
                timestamp=time.time(),
                value=value,
                refreshing=False,
            )
            self._cache.move_to_end(key)

            if len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def mark_refresh_complete(self, key: str):
        with self._lock:
            entry = self._cache.get(key)
            if entry:
                entry.refreshing = False

    def size(self):
        return len(self._cache)


class FPQLoadBalancer: 
    def __init__(self, num_instances: int = 2):
        self.pool: Queue[FairpriceQuerier] = Queue()
        for _ in range(num_instances):
            self.pool.put(FairpriceQuerier())
        
        # Start background thread for periodic pinging
        self.ping_thread = threading.Thread(target=self._ping_worker, daemon=True)
        self.ping_thread.start()

        self.max_workers = num_instances
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)

        self.cache = SWRLRUCache()

        COMMON_FOODS_FILE = "fairprice_common_search_terms_categorized.txt"
        # COMMON_FOODS_FILE = "common_foods_small.txt"

        with open(COMMON_FOODS_FILE, "r") as f:
            self.common_search_terms = [
                line.strip().lower()
                for line in f.readlines() if "#" not in line
            ]

    async def initialise(self):
        # Do initial caching
        await self.cache_search_terms(self.common_search_terms)
        self.cache.set_common(set(self.common_search_terms))

    async def cache_search_terms(self, search_terms):
        # Query products from FairPrice
        loop = asyncio.get_running_loop()

        tasks = [
            loop.run_in_executor(self.executor, self._query_selenium, term)
            for term in search_terms
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for term, result in zip(search_terms, results):
            if isinstance(result, Exception):
                    print(f"[CACHE ERROR] {term}: {result}")
            else:
                self.cache.set(term, result)

    def get(self, search_term: str) -> list[FairpriceItem]:
        search_term = search_term.strip().lower()

        cached_value, should_refresh = self.cache.get(search_term)

        # 1️⃣ Cache miss
        if cached_value is None:
            print("Cache miss")
            result = self._query_selenium(search_term)
            if result:
                self.cache.set(search_term, result)
            return result

        # 2️⃣ Cache hit
        if should_refresh:
            print("Cache hit stale. Background refresh")
            # Background refresh (non-blocking)
            threading.Thread(
                target=self._refresh_background,
                args=(search_term,),
                daemon=True
            ).start()
        print("Cache hit fresh")
        return cached_value

    def _refresh_background(self, search_term: str):
        try:
            result = self._query_selenium(search_term)
            if result:
                self.cache.set(search_term, result)
        finally:
            self.cache.mark_refresh_complete(search_term)

    def _query_selenium(self, search_term: str) -> list[FairpriceItem]:
        print("Querying:", search_term)
        FPQ = self.pool.get()  # Blocks until a driver is available
        try:
            result = FPQ.query(search_term)
            return result
        finally:
            self.pool.put(FPQ)

    # Do periodic pinging to keep the drivers alive, revive if necessary
    def ping_all(self) -> None:
        print("Pinging all FairpriceQuerier instances...")
        print("Current num cache entries:", self.cache.size())
        for _ in range(self.pool.qsize()):
            FPQ = self.pool.get()
            try:
                driver = FPQ.get_driver()
            finally:
                # print("Releasing driver back to pool...")
                self.pool.put(FPQ)

    def _ping_worker(self) -> None:
        """Background worker that pings all drivers every 5 minutes."""
        while True:
            time.sleep(300)  # 5 minutes
            self.ping_all()
