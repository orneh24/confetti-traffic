"""Full-page dashboard capture with the failing pair selected -> docs/img/dashboard-mock.jpg."""
import os
from playwright.sync_api import sync_playwright

os.makedirs("dev/run", exist_ok=True)   # temp PNGs; gitignored

with sync_playwright() as p:
    b = p.chromium.launch()
    # 5 nodes + the Hub column need the width
    pg = b.new_page(viewport={"width": 1680, "height": 1192})
    pg.goto("http://127.0.0.1:8199/")
    pg.wait_for_selector("td[data-src='node-3'][data-dst='node-5']")
    pg.click("td[data-src='node-3'][data-dst='node-5']")
    # The click scrolled the matrix sideways; bring the name and Hub columns back.
    pg.evaluate("document.querySelector('#matrix-section .section-body').scrollLeft = 0")
    pg.wait_for_timeout(1500)
    pg.screenshot(path="dev/run/dashboard-mock.png", full_page=True)
    b.close()

from PIL import Image
Image.open("dev/run/dashboard-mock.png").convert("RGB").save(
    "docs/img/dashboard-mock.jpg", quality=88, optimize=True)

print("wrote docs/img/dashboard-mock.jpg")
