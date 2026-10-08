"""Capture the Dashboard / Syslog / Timeline tour -> docs/img/hub-pages.gif.

Pages render at 1440x969 and are scaled to 960x646, with a caption bar under
each frame, matching the earlier GIF (960x690, 2.8 s per frame).
"""
import sys
import os
from playwright.sync_api import sync_playwright

os.makedirs("dev/run", exist_ok=True)   # temp PNGs; gitignored
from PIL import Image, ImageDraw, ImageFont

HUB = "http://127.0.0.1:8199"
W, H, BAR = 1440, 969, 44
FAILING = "td[data-src='ct-branch-7-wz1204'][data-dst='ct-site-a-xd2311']"


def scrub(pg, value):
    pg.evaluate("""v => { const s = document.getElementById('scrub');
                          s.value = v; s.dispatchEvent(new Event('input', {bubbles: true}));
                          s.dispatchEvent(new Event('change', {bubbles: true})); }""", value)
    pg.wait_for_timeout(800)


def frames(pg):
    pg.goto(HUB + "/")
    pg.wait_for_selector(FAILING)
    pg.wait_for_timeout(1200)
    yield "Dashboard: every path and every test at a glance"
    pg.click(FAILING)
    pg.wait_for_timeout(1200)
    yield "Dashboard: click a cell for that path's tests and history"
    # Mesh Settings starts folded; open it so the rules are in the frame.
    if "collapsed" in (pg.get_attribute("#settings-section", "class") or ""):
        pg.click(".collapse-toggle[data-section='settings-section']")
    pg.evaluate("document.getElementById('rule-list').scrollIntoView({block: 'center'})")
    pg.wait_for_timeout(600)
    yield "Dashboard: Mesh Settings and Mesh Rules shape what the mesh tests"
    pg.evaluate("window.scrollTo(0, 0)")
    pg.goto(HUB + "/syslog")
    pg.wait_for_timeout(1500)
    yield "Syslog: what the network devices logged"
    pg.goto(HUB + "/timeline")
    pg.wait_for_selector("#scrub")
    pg.wait_for_timeout(2000)
    scrub(pg, int(sys.argv[1]) if len(sys.argv) > 1 else 300)
    yield "Timeline: drag the slider to replay any earlier moment"
    scrub(pg, int(sys.argv[2]) if len(sys.argv) > 2 else 850)
    yield "Timeline: four paths fail after a router change"
    scrub(pg, 1000)
    yield "Timeline: incidents, with nearby syslog"
    pg.evaluate("localStorage.setItem('confetti-theme', 'confetti-night')")
    pg.goto(HUB + "/")
    pg.wait_for_selector(FAILING)
    pg.wait_for_timeout(1200)
    yield "Eight colour themes, each with its own confetti; this is Confetti Night"
    pg.evaluate("localStorage.removeItem('confetti-theme')")


def caption(img, text, font):
    out = Image.new("RGB", (img.width, img.height + BAR), (13, 17, 23))
    out.paste(img, (0, 0))
    d = ImageDraw.Draw(out)
    d.line([(0, img.height), (img.width, img.height)], fill=(45, 212, 191), width=2)
    d.text((14, img.height + 11), text, fill=(230, 237, 243), font=font)
    return out


def main():
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    shots = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": W, "height": H})
        for i, text in enumerate(frames(pg)):
            path = "dev/run/tour-%d.png" % i
            pg.screenshot(path=path)
            img = Image.open(path).convert("RGB").resize((960, 646), Image.LANCZOS)
            shots.append(caption(img, text, font))
        b.close()
    pal = [s.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
           for s in shots]
    pal[0].save("docs/img/hub-pages.gif", save_all=True, append_images=pal[1:],
                duration=2800, loop=0, optimize=True)
    print("frames:", len(shots), "-> wrote docs/img/hub-pages.gif")


main()
