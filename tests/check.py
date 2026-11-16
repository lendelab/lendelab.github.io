#!/usr/bin/env python3
"""Layout check for the built site. Usage: python tests/check.py [build_dir] [engine,engine,...]

Serves build_dir (default: public) on a local port, takes the page list from the built sitemaps and, in each engine,
loads every page at every width and checks overflow, clickable text broken over two lines, the phone menus, requests
to other sites (Fontshare, which serves Cabinet Grotesk, is the only one allowed), and hreflang reciprocity.
"""
import asyncio
import functools
import http.server
import pathlib
import re
import sys
import threading
import urllib.parse
import xml.etree.ElementTree as ET

from playwright.async_api import async_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "public")
ENGINES = (sys.argv[2] if len(sys.argv) > 2 else "chromium,firefox,webkit").split(",")
WIDTHS = [320, 375, 414, 768, 959, 960, 1280, 1440]
SITE = "https://lendelab.github.io"
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}

OVERFLOW_JS = """() => {
  const de = document.documentElement;
  const wide = [];
  for (const el of document.querySelectorAll('body *')) {
    if (el.ownerSVGElement || el.closest('.vh')) continue;
    const r = el.getBoundingClientRect();
    if (r.width > 0 && (r.right > de.clientWidth + 1 || r.left < -1)) {
      wide.push(el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).join('.') : '')
                + ` [${Math.round(r.left)},${Math.round(r.right)}]`);
    }
  }
  return {scrollW: de.scrollWidth, clientW: de.clientWidth, offenders: wide.slice(0, 6)};
}"""

# clickable text that must stay on one line: navigation, buttons, footer links, icon links, arrow links, event links
WRAP_JS = """() => {
  const sel = '.mast__links a, .mast__lang, .mast__toggle, .bar__link, .bar__lang, .btn, .btn--fill, .skip, .foot__links a, .icons a, .more, .facts a.nowrap, .contact a';
  const bad = [];
  for (const el of document.querySelectorAll(sel)) {
    if (el.offsetParent === null) continue;
    if (el.getClientRects().length > 1) bad.push(el.textContent.trim().slice(0, 40));
  }
  return bad;
}"""

PANEL_JS = """(sel) => {
  const de = document.documentElement;
  const out = {over: [], wrap: [], small: [], panel: null};
  const panel = document.querySelector(sel);
  if (!panel || panel.offsetParent === null) return out;
  const p = panel.getBoundingClientRect();
  out.panel = [Math.round(p.left), Math.round(p.right)];
  for (const el of panel.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && (r.right > de.clientWidth + 1 || r.left < -1)) out.over.push(el.tagName.toLowerCase());
  }
  for (const a of panel.querySelectorAll('a')) {
    if (a.getClientRects().length > 1) out.wrap.push(a.textContent.trim().slice(0, 30));
    const r = a.getBoundingClientRect();
    if (r.height < 44 || r.width < 24) out.small.push(a.textContent.trim().slice(0, 20));
  }
  return out;
}"""

VISIBLE_JS = """(sel) => { const el = document.querySelector(sel); return !!el && el.offsetParent !== null && !el.closest('[inert]'); }"""


def sitemap_pages():
    pages = []
    index = ET.parse(BUILD / "sitemap.xml").getroot()
    maps = [l.text for l in index.findall("s:sitemap/s:loc", NS)] or [SITE + "/sitemap.xml"]
    for m in maps:
        tree = ET.parse(BUILD / urllib.parse.urlparse(m).path.lstrip("/"))
        pages += [urllib.parse.urlparse(l.text).path for l in tree.getroot().findall("s:url/s:loc", NS)]
    return sorted(set(pages))


def allowed_hosts():
    hosts = {"127.0.0.1", "api.fontshare.com", "cdn.fontshare.com"}
    site = (ROOT / "data" / "site.yaml").read_text(encoding="utf-8")
    m = re.search(r'^goatcounter:\s*"?([A-Za-z0-9-]+)"?\s*$', site, re.M)
    if m:
        hosts.add(f"{m.group(1)}.goatcounter.com")
    return hosts


def hreflang_problems(base, pages):
    import urllib.request
    links = {}
    for path in pages:
        html = urllib.request.urlopen(base + path).read().decode("utf-8")
        alts = {}
        for tag in re.findall(r"<link[^>]+>", html):
            if re.search(r"rel=\"?alternate", tag) and "hreflang" in tag:
                lang = re.search(r"hreflang=\"?([\w-]+)", tag).group(1)
                href = re.search(r"href=\"?([^\" >]+)", tag).group(1)
                alts[lang] = urllib.parse.urlparse(href).path
        canon = re.search(r"<link[^>]+rel=\"?canonical[^>]*>", html)
        links[path] = (alts, canon.group(0) if canon else "")
    fails = []
    for path, (alts, canon) in links.items():
        if f'{SITE}{path}' not in canon:
            fails.append(f"{path}: canonical does not point to itself")
        if path not in alts.values():
            fails.append(f"{path}: no hreflang entry for itself")
        if "x-default" not in alts:
            fails.append(f"{path}: no x-default")
        for lang, target in alts.items():
            if lang == "x-default" or target == path:
                continue
            back = links.get(target)
            if back is None:
                fails.append(f"{path}: hreflang {lang} -> {target}, which is not in the sitemap")
            elif path not in back[0].values():
                fails.append(f"{path}: hreflang {lang} -> {target}, which does not link back")
    return fails


async def run_engine(p, name, base, pages, hosts):
    fails = []
    browser = await getattr(p, name).launch()
    ctx = await browser.new_context(color_scheme="light")
    page = await ctx.new_page()
    page.set_default_navigation_timeout(90000)
    foreign = []
    page.on("request", lambda r: foreign.append(r.url) if urllib.parse.urlparse(r.url).hostname not in hosts else None)
    for path in pages:
        for w in WIDTHS:
            await page.set_viewport_size({"width": w, "height": 900})
            resp = await page.goto(base + path, wait_until="load")
            if resp is None or resp.status not in (200, 304):
                fails.append(f"{name} {path} -> HTTP {resp.status if resp else 'none'}")
                continue
            await page.evaluate("document.fonts.ready")
            o = await page.evaluate(OVERFLOW_JS)
            if o["scrollW"] > o["clientW"] + 1:
                fails.append(f"{name} {path} @{w}: scrollWidth {o['scrollW']} > {o['clientW']} :: {o['offenders']}")
            elif o["offenders"]:
                fails.append(f"{name} {path} @{w}: element past viewport :: {o['offenders']}")
            wrapped = await page.evaluate(WRAP_JS)
            if wrapped:
                fails.append(f"{name} {path} @{w}: clickable text on two lines :: {wrapped}")
            # the masthead's own menu at rest (shown below 72rem)
            if await page.evaluate(VISIBLE_JS, ".mast__toggle"):
                await page.click(".mast__toggle")
                m = await page.evaluate(PANEL_JS, ".mast__row[data-open] .mast__links")
                fails += check_panel(name, path, w, "row menu", m)
                await page.keyboard.press("Escape")
                if await page.evaluate("document.activeElement && document.activeElement.classList.contains('mast__toggle')") is not True:
                    fails.append(f"{name} {path} @{w}: Escape did not return focus to the row toggle")
            # the frosted bar's Menú sheet past the fold (shown below 77rem)
            await page.evaluate("window.scrollTo(0, document.querySelector('.fold').offsetHeight + 400)")
            await page.wait_for_timeout(450)
            if await page.evaluate(VISIBLE_JS, ".bar__menu"):
                await page.click(".bar__menu")
                m = await page.evaluate(PANEL_JS, "#sheet")
                fails += check_panel(name, path, w, "bar sheet", m)
                await page.keyboard.press("Escape")
                if await page.evaluate("document.activeElement && document.activeElement.classList.contains('bar__menu')") is not True:
                    fails.append(f"{name} {path} @{w}: Escape did not return focus to the bar toggle")
            if foreign:
                fails.append(f"{name} {path} @{w}: requests to other sites :: {sorted(set(foreign))[:4]}")
                foreign.clear()
    await browser.close()
    return fails


def check_panel(name, path, w, label, m):
    out = []
    if m["panel"] is None:
        return [f"{name} {path} @{w}: {label} did not open"]
    if m["over"]:
        out.append(f"{name} {path} @{w}: {label} past viewport :: {m['over'][:4]}")
    if m["wrap"]:
        out.append(f"{name} {path} @{w}: {label} link wraps :: {m['wrap']}")
    if m["small"]:
        out.append(f"{name} {path} @{w}: {label} target under 44px :: {m['small']}")
    if m["panel"][0] != 0 or m["panel"][1] != w:
        out.append(f"{name} {path} @{w}: {label} does not span the viewport :: {m['panel']}")
    return out


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class Server(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        pass  # browsers drop connections when a navigation interrupts a download


async def main():
    server = Server(("127.0.0.1", 0), functools.partial(Quiet, directory=str(BUILD)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    pages = sitemap_pages()
    hosts = allowed_hosts()
    fails = hreflang_problems(base, pages)
    async with async_playwright() as p:
        results = await asyncio.gather(*(run_engine(p, e, base, pages, hosts) for e in ENGINES))
    for name, r in zip(ENGINES, results):
        print(f"{name}: {'clean' if not r else f'{len(r)} problems'}")
        fails += r
    server.shutdown()
    if fails:
        print(f"{len(fails)} problems:")
        for f in fails[:200]:
            print("  -", f)
        sys.exit(1)
    print(f"clean: {len(pages)} pages x {len(WIDTHS)} widths x {len(ENGINES)} engines, menus open and closed, "
          f"no requests to other sites except Fontshare, hreflang reciprocal")


asyncio.run(main())
