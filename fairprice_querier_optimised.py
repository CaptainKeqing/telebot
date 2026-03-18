"""
FairPrice Querier — httpx rewrite
------------------------------------------------
Strategy:

Direct httpx call to FairPrice's internal search API.
Zero browser overhead; much faster and more scalable.


How the API endpoint was discovered:
  Open DevTools → Network → XHR/Fetch while searching on fairprice.com.sg.
  The site calls:
    1) GET https://website-api.omni.fairprice.com.sg/api/product/v2     # Gives products, but no sorting
        ?query=<term>&size=10&page=1&storeId=&orderType=pickup&...
    2) https://website-api.omni.fairprice.com.sg/api/layout/search/v2   # Gives products, but with optional sorting parameter (very useful)
        ?algopers=prm-ppb-1%2Cprm-ep-1%2Ct-epds-1%2Ct-ppb-0%2Ct...
    3) https://website-api.omni.fairprice.com.sg/api/suggestions        # Gives alternate search suggestions
        ?experiments=ls_deltime-sortA%2CsearchVariant-B%2Cgv-B%...
  with no auth headers required for basic search results.
  If this ever breaks, run `intercept_and_print_api_url()` below once to
  re-discover the current endpoint.
"""

import asyncio
import threading
import time
import httpx

from collections import OrderedDict
from dataclasses import dataclass
from typing import NamedTuple, Optional

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class FairpriceItem(NamedTuple):
    image_url: str
    item_name: str
    item_price: str
    promoPrice: Optional[str] = None
    promoDescription: Optional[str] = None

    # helper function to print nicely
    def __str__(self):
        promo = f" (Promo: {self.promoDescription})" if self.promoDescription else ""
        return f"{self.item_name} - {self.item_price}{promo}"


# ---------------------------------------------------------------------------
# API constants  (update if FairPrice changes their backend)
# ---------------------------------------------------------------------------

_API_BASE = "https://website-api.omni.fairprice.com.sg/api/layout/search/v2"
_API_PARAMS = {
    "orderType": "DELIVERY",
    "sorting": "RELEVANCE",
}
_HEADERS = {
    "Referer": "https://www.fairprice.com.sg/", # Not strictly necessary, but just in case they check for referer in future
}

# ---------------------------------------------------------------------------
# Primary path — httpx (no browser)
# ---------------------------------------------------------------------------

def _query_api(search_term: str, max_results: int = 20) -> list[FairpriceItem]:
    """
    Call FairPrice's internal REST API directly.
    Returns up to 10 FairpriceItems, or raises on failure.
    """
    params = {**_API_PARAMS, "q": search_term} # q stands for query.get("data", {})
    with httpx.Client(timeout=10, follow_redirects=True) as client:
        r = client.get(_API_BASE, params=params, headers=_HEADERS)
        r.raise_for_status()

    data = r.json()
    if len(data["data"]["page"]["layouts"]) < 3:
        raise ValueError("Unexpected API response structure, most likely the item count is 0")

    suggested_terms = data["data"]["page"]["layouts"][1]["value"]["collection"] # Might be useful for autocomplete in future, but ignore for now
    items = data["data"]["page"]["layouts"][2]["value"]["collection"]["product"]
    top_items = items[:min(max_results, len(items))]

    results: list[FairpriceItem] = []
    for p in top_items:
        name = p.get("name", "")
        image = p.get("images", [{}])[0] if p.get("images") else "" # 0 index is the front facing image, they provide all 4 sides

        # Base prices live under "final_price" (Lol why did they name it final)
        # Offer prices live under offers[].price. There can also be a description under offers[].shortDescriptionA
        price = p.get("final_price")
        promoPrice = None
        promoDescription = None
        offers = p.get("offers", [])
        if offers:
            promoPrice = offers[0].get("price")
            promoDescription = offers[0].get("shortDescriptionA")

        if name:
            results.append(
                FairpriceItem(
                    image_url=image, 
                    item_name=name, 
                    item_price=price, 
                    promoPrice=promoPrice, 
                    promoDescription=promoDescription))

    return results

# ---------------------------------------------------------------------------
# Cache (unchanged SWR-LRU logic from original)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CacheEntry:
    timestamp: float
    value: list
    refreshing: bool = False


class SWRLRUCache:
    def __init__(self, max_size: int = 10_000, ttl: int = 3600, common_ttl: int = 86400):
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
            if age > ttl * 2:
                del self._cache[key]
                return None, False
            if age > ttl:
                refresh = not entry.refreshing
                if refresh:
                    entry.refreshing = True
                self._cache.move_to_end(key)
                return entry.value, refresh
            self._cache.move_to_end(key)
            return entry.value, False

    def set(self, key: str, value: list):
        if not value:
            return
        with self._lock:
            self._cache[key] = CacheEntry(timestamp=time.time(), value=value)
            self._cache.move_to_end(key)
            if len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def mark_refresh_complete(self, key: str):
        with self._lock:
            entry = self._cache.get(key)
            if entry:
                entry.refreshing = False

    def size(self) -> int:
        return len(self._cache)


# ---------------------------------------------------------------------------
# Public interface — FPQLoadBalancer (drop-in replacement)
# ---------------------------------------------------------------------------

class FPQLoadBalancer:
    """
    Drop-in replacement for the original FPQLoadBalancer.
    - Uses httpx (no browser) for all queries.
    - Retains the same SWR-LRU cache and common-term pre-warming.
    """

    def __init__(self):
        self.cache = SWRLRUCache()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bg_thread: threading.Thread | None = None
        self._start_event_loop()

        COMMON_FOODS_FILE = "fairprice_common_search_terms_categorized.txt"
        with open(COMMON_FOODS_FILE, "r") as f:
            self.common_search_terms = [
                line.strip().lower()
                for line in f if "#" not in line and line.strip()
            ]

    # ------------------------------------------------------------------
    # Internal async helpers
    # ------------------------------------------------------------------

    def _start_event_loop(self):
        """Run a private asyncio event loop in a background thread."""
        self._loop = asyncio.new_event_loop()
        self._bg_thread = threading.Thread(
            target=self._loop.run_forever, daemon=True
        )
        self._bg_thread.start()

        # Schedule periodic pings every 5 minutes
        async def _ping_loop():
            while True:
                await asyncio.sleep(300)
                print("[Ping] cache size:", self.cache.size())

        asyncio.run_coroutine_threadsafe(_ping_loop(), self._loop)

    def _run(self, coro):
        """Submit a coroutine to the background loop and block until done."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    # ------------------------------------------------------------------
    # Query logic
    # ------------------------------------------------------------------

    async def _query_async(self, search_term: str) -> list[FairpriceItem]:
        """Try httpx first; fall back to Playwright on any error."""
        try:
            loop = asyncio.get_running_loop()
            # httpx is sync — run in executor to avoid blocking the event loop
            result = await loop.run_in_executor(None, _query_api, search_term)
            print(f"[API] {search_term} → {len(result)} items")
            return result
            # print(f"[API] {search_term} → empty, falling back to Playwright")
        except Exception as e:
            print(f"[API] {search_term} failed ({e})")
            return []  # Return empty list on failure; 

    def _query(self, search_term: str) -> list[FairpriceItem]:
        return self._run(self._query_async(search_term))

    # ------------------------------------------------------------------
    # Public API (same interface as original FPQLoadBalancer)
    # ------------------------------------------------------------------

    async def initialise(self):
        """Pre-warm cache with common search terms."""
        print(f"[Init] Pre-warming {len(self.common_search_terms)} terms...")
        tasks = [self._query_async(term) for term in self.common_search_terms]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for term, result in zip(self.common_search_terms, results):
            if isinstance(result, Exception):
                print(f"[Init ERROR] {term}: {result}")
            else:
                self.cache.set(term, result)
        self.cache.set_common(set(self.common_search_terms))
        print("[Init] Done.")

    def get(self, search_term: str) -> list[FairpriceItem]:
        search_term = search_term.strip().lower()
        cached_value, should_refresh = self.cache.get(search_term)

        if cached_value is None:
            print("[Cache] miss:", search_term)
            result = self._query(search_term)
            if result:
                self.cache.set(search_term, result)
            return result

        if should_refresh:
            print("[Cache] stale, background refresh:", search_term)
            asyncio.run_coroutine_threadsafe(
                self._refresh_background(search_term), self._loop
            )

        return cached_value

    async def _refresh_background(self, search_term: str):
        try:
            result = await self._query_async(search_term)
            if result:
                self.cache.set(search_term, result)
        finally:
            self.cache.mark_refresh_complete(search_term)
