from typing import NamedTuple
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains


class FairpriceItem(NamedTuple):
    image_url: str
    item_name: str
    item_price: str

class FairpriceQuerier:

    def __init__(self):
        self.WEBSITE = "https://www.fairprice.com.sg/search?query="
        self.NET_PRICE_XPATH = "//span[@class='sc-ab6170a9-1 sc-65bf849-1 gDJNWQ cXCGWM']"
        self.PRODUCT_IMAGE_XPATH = '//img[@class="sc-aca6d870-0 janHcI"]' # Also contains product name

        self.driver = webdriver.Chrome() # Do we need to quit()?
        
    def query(self, search_term: str) -> list[FairpriceItem]:
        urlsafe_query = quote(search_term)
        self.driver.get(self.WEBSITE + urlsafe_query)
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