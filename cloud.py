"""
tempmail_playwright_threaded.py (mit Proxy-Support)

- Uses temp-mail API to generate disposable emails.
- Uses Playwright to drive the Filen.io registration UI.
- Supports concurrent account creation with threads.
- Supports optional proxies loaded from proxies.txt (proxytype://host:port).
  Each proxy is used up to MAX_PROXY_USES times (default 15), dann wird er nicht mehr verwendet.
- Proxies können wahlweise nur für den Browser oder auch für TempMail genutzt werden.
- Saves accounts in accounts.txt as email:password.

Requirements:
    pip install playwright requests pysocks
    playwright install
"""

import asyncio
import time
import random
import string
import requests
import threading
from queue import Queue
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# -------------------------
# Config
# -------------------------
# Wenn False: Proxies werden NUR für den Browser benutzt, nicht für TempMail (requests)
# Wenn True:  Proxies werden für ALLES benutzt (Browser + E-Mail)
USE_PROXIES_FOR_EMAIL = False

# Temp mail endpoints
MAIL_ENDPOINT = "https://api.internal.temp-mail.io/api/v3/email/new"
INBOX_ENDPOINT = "https://api.internal.temp-mail.io/api/v3/email/{email}/messages"

# Filen referral page
INITIAL_REFERRAL_URL = "https://filen.io/r/cbe16b147f3975e59177f12b2c37eb68"

# Polling settings
INBOX_POLL_INTERVAL = 5.0
INBOX_MAX_ATTEMPTS = 60  # up to 5 minutes

# Proxy settings
PROXIES_LIST = None               # list of proxy strings
PROXY_USAGE = {}                  # proxy -> usage count
PROXY_LOCK = threading.Lock()
PROXY_INDEX = 0                   # for round-robin
MAX_PROXY_USES = 15               # use each proxy this many times, then retire


def load_proxies(filename="proxies.txt"):
    """
    Read proxies from file. Each non-empty line must contain '://', e.g.:
    socks5://1.2.3.4:1080
    http://5.6.7.8:8080
    """
    proxies = []
    try:
        with open(filename, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                if "://" not in line:
                    print(f"[Proxy] Ignoring invalid line (missing scheme): {line}")
                    continue
                proxies.append(line)
    except FileNotFoundError:
        print(f"[Proxy] {filename} not found. Continuing without proxies.")
    if not proxies:
        return None
    # init usage
    with PROXY_LOCK:
        global PROXY_USAGE
        PROXY_USAGE = {p: 0 for p in proxies}
    return proxies


def get_next_proxy():
    """
    Thread-safe retrieval of the next available proxy (round-robin),
    increasing its usage count. Returns None if no proxy available / proxies disabled.
    Each proxy will be used at most MAX_PROXY_USES times.
    """
    global PROXY_INDEX, PROXIES_LIST, PROXY_USAGE
    with PROXY_LOCK:
        if not PROXIES_LIST:
            return None
        available = [p for p, cnt in PROXY_USAGE.items() if cnt < MAX_PROXY_USES]
        if not available:
            # all exhausted
            print("[Proxy] All proxies exhausted.")
            return None
        n = len(PROXIES_LIST)
        # Try up to n times to find an available proxy using PROXY_INDEX
        for _ in range(n):
            p = PROXIES_LIST[PROXY_INDEX % n]
            PROXY_INDEX = (PROXY_INDEX + 1) % n
            cnt = PROXY_USAGE.get(p, 0)
            if cnt < MAX_PROXY_USES:
                PROXY_USAGE[p] = cnt + 1
                if PROXY_USAGE[p] >= MAX_PROXY_USES:
                    print(f"[Proxy] Proxy exhausted: {p} (used {PROXY_USAGE[p]} times)")
                else:
                    print(f"[Proxy] Assigned proxy {p} (use {PROXY_USAGE[p]}/{MAX_PROXY_USES})")
                return p
        # fallback: return first available (shouldn't normally happen)
        p = available[0]
        PROXY_USAGE[p] += 1
        print(f"[Proxy] Assigned proxy {p} (use {PROXY_USAGE[p]}/{MAX_PROXY_USES})")
        return p


# -------------------------
# TempMailService
# -------------------------
class TempMailService:
    def __init__(self, proxy=None):
        self.email = None
        self.proxy = proxy  # string like 'socks5://1.2.3.4:1080' or 'http://x.y.z:8080'

    def _requests_proxies(self):
        if not USE_PROXIES_FOR_EMAIL:
            return None
        if not self.proxy:
            return None
        # map both http and https to same proxy
        return {"http": self.proxy, "https": self.proxy}

    def generate_email(self):
        try:
            data = {"min_name_length": 10, "max_name_length": 10}
            resp = requests.post(MAIL_ENDPOINT, json=data, timeout=15, proxies=self._requests_proxies())
            resp.raise_for_status()
            email = resp.json().get("email")
            if email and "@" in email:
                self.email = email
                username, domain = email.split("@", 1)
                return email, username, domain
        except Exception as e:
            print(f"[TempMail] Error generating email (proxy={self.proxy if USE_PROXIES_FOR_EMAIL else 'DIRECT'}): {e}")
        return None, None, None

    def check_inbox_for_activation_link(self, max_attempts=INBOX_MAX_ATTEMPTS):
        if not self.email:
            return None

        for attempt in range(1, max_attempts + 1):
            try:
                url = INBOX_ENDPOINT.format(email=self.email)
                resp = requests.get(url, timeout=15, proxies=self._requests_proxies())
                resp.raise_for_status()
                messages = resp.json() or []

                for msg in messages:
                    if "filen" in (msg.get("from") or "").lower():
                        body = (
                            msg.get("body_text")
                            or msg.get("body")
                            or msg.get("text")
                            or msg.get("body_html")
                            or ""
                        )
                        activation = extract_activation_link(body)
                        if activation:
                            return activation

                time.sleep(INBOX_POLL_INTERVAL)
            except Exception as e:
                print(f"[TempMail] Error checking inbox (proxy={self.proxy if USE_PROXIES_FOR_EMAIL else 'DIRECT'}): {e}")
                time.sleep(INBOX_POLL_INTERVAL)
        return None


# -------------------------
# Helpers
# -------------------------
def extract_activation_link(body: str):
    import re
    pattern = r"https://filen\.io/activate/[a-f0-9]{32}"
    m = re.search(pattern, body or "")
    return m.group(0) if m else None


def generate_secure_password(length=12):
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(random.choice(chars) for _ in range(length))


def save_account(email, password, filename="accounts.txt"):
    with open(filename, "a", encoding="utf-8") as f:
        f.write(f"{email}:{password}\n")
    print(f"[Save] {email}:{password}")


def compute_window_positions(threads, screen_w=1920, screen_h=1080):
    cols = int(threads**0.5) or 1
    rows = (threads + cols - 1) // cols
    win_w = max(400, screen_w // cols)
    win_h = max(300, screen_h // rows)
    positions = []
    for r in range(rows):
        for c in range(cols):
            x = c * win_w
            y = r * win_h
            positions.append(((x, y), (win_w, win_h)))
    return positions[:threads]


async def safe_fill(page, selector, value):
    elem = await page.wait_for_selector(selector, timeout=10000)
    await elem.click()
    await elem.fill("")   # clear any junk
    await elem.type(value, delay=50)  # simulate typing


# -------------------------
# Browser flow
# -------------------------
async def try_create_account(index, email, password, headless, window_pos, window_size, proxy):
    """
    Launches Playwright browser. If proxy is not None, passes it to playwright.launch via browser_args["proxy"].
    """
    async with async_playwright() as p:
        args = ["--no-sandbox"]
        if not headless:
            args.append(f"--window-position={window_pos[0]},{window_pos[1]}")
            args.append(f"--window-size={window_size[0]},{window_size[1]}")

        browser_args = {"headless": headless, "args": args}
        if proxy:
            browser_args["proxy"] = {"server": proxy}

        browser = await p.chromium.launch(**browser_args)
        ctx = await browser.new_context(locale="en-US")
        page = await ctx.new_page()

        tm = TempMailService(proxy=proxy if USE_PROXIES_FOR_EMAIL else None)
        tm.email = email

        try:
            await page.goto(INITIAL_REFERRAL_URL, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.locator('a[href="https://app.filen.io/#/register"]').first.click(timeout=30000)
                print(f"[Acc {index}] Clicked register link")
            except PlaywrightTimeoutError:
                try:
                    link = page.locator('a[href*="#/register"]')
                    if await link.count() > 0:
                        await link.first.click(timeout=30000)
                        print(f"[Acc {index}] Clicked register link (by href)")
                    else:
                        await page.get_by_role("link", name="Get started for free").click(timeout=30000)
                        print(f"[Acc {index}] Clicked register link (by text)")
                except PlaywrightTimeoutError:
                    print(f"[Acc {index}] Could not find register link.")
                    await browser.close()
                    return False

            await page.wait_for_selector("input#email", timeout=30000)

            try:
                accept_btn = await page.wait_for_selector('button:has-text("Accept")', timeout=5000)
                if accept_btn:
                    await accept_btn.click()
                    await asyncio.sleep(0.5)
            except PlaywrightTimeoutError:
                pass

            await safe_fill(page, "input#email", email)
            await safe_fill(page, "input#password", password)
            await safe_fill(page, "input#confirmPassword", password)
            
            await page.get_by_role("button", name="Create account").click(timeout=10000)
            print(f"[Acc {index}] Filled out the registration fields! (proxy={proxy})")

            print(f"[Acc {index}] Getting confirmation email... (proxy={proxy if USE_PROXIES_FOR_EMAIL else 'DIRECT'})")
            activation = tm.check_inbox_for_activation_link()
            if not activation:
                print(f"[Acc {index}] No activation link received.")
                await browser.close()
                return False

            await page.goto(activation, wait_until="networkidle", timeout=30000)

            await browser.close()
            return True

        except Exception as e:
            print(f"[Acc {index}] Error: {e}")
            try:
                await browser.close()
            except:
                pass
            return False


async def create_single_account(index, headless, window_pos, window_size, proxy):
    tm = TempMailService(proxy=proxy if USE_PROXIES_FOR_EMAIL else None)
    email, _, _ = tm.generate_email()
    if not email:
        print(f"[Acc {index}] Failed to generate email. (proxy={proxy if USE_PROXIES_FOR_EMAIL else 'DIRECT'})")
        return False

    password = generate_secure_password()
    print(f"[Acc {index}] Email: {email}  Password: {password}  Proxy: {proxy}")

    for attempt in range(1, 3):
        success = await try_create_account(index, email, password, headless, window_pos, window_size, proxy)
        if success:
            save_account(email, password)
            return True
        else:
            print(f"[Acc {index}] Attempt {attempt} failed. (proxy={proxy})")
    print(f"[Acc {index}] Discarded after 2 failed attempts. (proxy={proxy})")
    return False


# -------------------------
# Threaded worker
# -------------------------
def thread_worker(thread_id, job_queue, headless, positions, results):
    async def run_jobs():
        local_results = []
        while not job_queue.empty():
            try:
                acc_index = job_queue.get_nowait()
            except:
                break
            pos, size = positions[thread_id % len(positions)]
            proxy = get_next_proxy()
            success = await create_single_account(acc_index, headless, pos, size, proxy)
            local_results.append(success)
            job_queue.task_done()
        results.extend(local_results)

    asyncio.run(run_jobs())


# -------------------------
# Main entry
# -------------------------
def main():
    try:
        total_accounts = int(input("How many accounts do you want to create? ").strip())
    except ValueError:
        total_accounts = 1

    try:
        threads = int(input("How many threads (parallel browsers)? ").strip())
    except ValueError:
        threads = 1

    see_browser = input("Do you want to see the browsers? (y/n, default n): ").strip().lower()
    headless = not (see_browser == "y")

    use_proxies = input("Do you want to use proxies? (y/n, default n): ").strip().lower()
    global PROXIES_LIST
    PROXIES_LIST = load_proxies() if use_proxies == "y" else None

    if PROXIES_LIST:
        print(f"[Main] Loaded {len(PROXIES_LIST)} proxies. Each will be used up to {MAX_PROXY_USES} times.")
    else:
        print("[Main] Proxies disabled or none loaded; running without proxies.")

    print(f"\n[Main] Creating {total_accounts} accounts with {threads} threads (headless={headless}, proxies={'ON' if PROXIES_LIST else 'OFF'})...\n")

    job_queue = Queue()
    for i in range(1, total_accounts + 1):
        job_queue.put(i)

    positions = compute_window_positions(threads)

    thread_list = []
    results = []

    for tid in range(threads):
        t = threading.Thread(target=thread_worker, args=(tid, job_queue, headless, positions, results))
        t.start()
        thread_list.append(t)

    for t in thread_list:
        t.join()

    created = sum(1 for r in results if r)
    print(f"\n[Main] Finished. Successfully created {created}/{total_accounts} accounts.\n")


if __name__ == "__main__":
    main()
