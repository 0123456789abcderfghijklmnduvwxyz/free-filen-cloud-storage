"""
tempmail_playwright_threaded.py

- Uses temp-mail API to generate disposable emails.
- Uses Playwright to drive the Filen.io registration UI.
- Supports concurrent account creation with threads.
- Retries once per account with same email/password, then discards it if it still fails.
- Saves accounts in accounts.txt as email:password.

Requirements:
    pip install playwright requests
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

# Temp mail endpoints
MAIL_ENDPOINT = "https://api.internal.temp-mail.io/api/v3/email/new"
INBOX_ENDPOINT = "https://api.internal.temp-mail.io/api/v3/email/{email}/messages"

# Filen referral page
INITIAL_REFERRAL_URL = "https://filen.io/r/cbe16b147f3975e59177f12b2c37eb68"

# Polling settings
INBOX_POLL_INTERVAL = 5.0
INBOX_MAX_ATTEMPTS = 60  # up to 5 minutes


# -------------------------
# TempMailService
# -------------------------
class TempMailService:
    def __init__(self):
        self.email = None

    def generate_email(self):
        try:
            data = {"min_name_length": 10, "max_name_length": 10}
            resp = requests.post(MAIL_ENDPOINT, json=data, timeout=15)
            resp.raise_for_status()
            email = resp.json().get("email")
            if email and "@" in email:
                self.email = email
                username, domain = email.split("@", 1)
                return email, username, domain
        except Exception as e:
            print(f"[TempMail] Error generating email: {e}")
        return None, None, None

    def check_inbox_for_activation_link(self, max_attempts=INBOX_MAX_ATTEMPTS):
        if not self.email:
            return None

        for attempt in range(1, max_attempts + 1):
            try:
                url = INBOX_ENDPOINT.format(email=self.email)
                resp = requests.get(url, timeout=15)
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
                print(f"[TempMail] Error checking inbox: {e}")
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


# -------------------------
# Browser flow
# -------------------------
async def try_create_account(index, email, password, headless, window_pos, window_size):
    async with async_playwright() as p:
        args = ["--no-sandbox"]
        if not headless:
            args.append(f"--window-position={window_pos[0]},{window_pos[1]}")
            args.append(f"--window-size={window_size[0]},{window_size[1]}")

        browser = await p.chromium.launch(headless=headless, args=args)
        ctx = await browser.new_context(locale="en-US")  # force English site
        page = await ctx.new_page()

        tm = TempMailService()
        tm.email = email

        try:
            # Go to referral page
            await page.goto(INITIAL_REFERRAL_URL, wait_until="domcontentloaded", timeout=60000)

            # Click the register link
            try:
                await page.locator('a[href="https://app.filen.io/#/register"]').first.click(timeout=30000)
                print(f"[Acc {index}] Clicked register link")
            except PlaywrightTimeoutError:
                print(f"[Acc {index}] Could not find register link.")
                await browser.close()
                return False

            # Try multiple ways to click the register link
            try:
                # First try by href
                link = page.locator('a[href*="#/register"]')
                if await link.count() > 0:
                    await link.first.click(timeout=30000)
                    print(f"[Acc {index}] Clicked register link (by href)")
                else:
                    # Fallback: look by visible text
                    await page.get_by_role("link", name="Get started for free").click(timeout=30000)
                    print(f"[Acc {index}] Clicked register link (by text)")
            except PlaywrightTimeoutError:
                print(f"[Acc {index}] Could not find register link.")
                await browser.close()
                return False


            # Wait for form
            await page.wait_for_selector("input#email", timeout=30000)

            # Click "Accept" if present (cookie consent)
            accept_btn = await page.query_selector('button:has-text("Accept")')
            if accept_btn:
                await accept_btn.click()
                await asyncio.sleep(0.5)

            # Fill fields
            await page.fill("input#email", email)
            await page.fill("input#password", password)
            await page.fill("input#confirmPassword", password)

            # Click "Create account"
            await page.get_by_role("button", name="Create account").click(timeout=10000)

            # Poll for activation email
            activation = tm.check_inbox_for_activation_link()
            if not activation:
                print(f"[Acc {index}] No activation link received.")
                await browser.close()
                return False

            # Visit activation link
            await page.goto(activation, wait_until="networkidle", timeout=30000)

            await browser.close()
            return True

        except Exception as e:
            print(f"[Acc {index}] Error: {e}")
            await browser.close()
            return False


async def create_single_account(index, headless, window_pos, window_size):
    tm = TempMailService()
    email, _, _ = tm.generate_email()
    if not email:
        print(f"[Acc {index}] Failed to generate email.")
        return False

    password = generate_secure_password()
    print(f"[Acc {index}] Email: {email}  Password: {password}")

    # Retry logic (max 2 attempts: first + one retry)
    for attempt in range(1, 3):
        success = await try_create_account(index, email, password, headless, window_pos, window_size)
        if success:
            save_account(email, password)
            return True
        else:
            print(f"[Acc {index}] Attempt {attempt} failed.")
    print(f"[Acc {index}] Discarded after 2 failed attempts.")
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
            success = await create_single_account(acc_index, headless, pos, size)
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

    print(f"\n[Main] Creating {total_accounts} accounts with {threads} threads (headless={headless})...\n")

    # Shared job queue
    job_queue = Queue()
    for i in range(1, total_accounts + 1):
        job_queue.put(i)

    positions = compute_window_positions(threads)

    # Launch threads
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
