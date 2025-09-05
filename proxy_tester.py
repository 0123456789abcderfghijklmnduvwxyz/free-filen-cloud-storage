import requests
import concurrent.futures

INPUT_FILE = "proxies.txt"
OUTPUT_FILE = "working_proxies.txt"
TEST_URL = "https://ifconfig.me"
TIMEOUT = 10


def test_proxy(proxy: str) -> tuple[str, bool]:
    """
    Testet einen Proxy mit einem HTTPS-Request auf ifconfig.me.
    Gibt (proxy, True/False) zurück.
    """
    proxy = proxy.strip()
    if not proxy or "://" not in proxy:
        return proxy, False

    scheme = proxy.split("://", 1)[0].lower()

    # requests benötigt dict {"http": proxy, "https": proxy}
    if scheme in ["http", "https", "socks4", "socks5"]:
        proxies = {"http": proxy, "https": proxy}
    else:
        return proxy, False

    try:
        r = requests.get(TEST_URL, proxies=proxies, timeout=TIMEOUT)
        if r.status_code == 200:
            print(f"[OK] {proxy} -> {r.text.strip()}")
            return proxy, True
    except Exception as e:
        print(f"[FAIL] {proxy} -> {e.__class__.__name__}: {e}")

    return proxy, False


def main():
    try:
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            proxies = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"{INPUT_FILE} not found!")
        return

    print(f"Testing {len(proxies)} proxies...")

    working = []
    # parallel testen (20 Threads)
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(test_proxy, proxies))

    # nur funktionierende übernehmen
    for proxy, ok in results:
        if ok:
            working.append(proxy)

    # speichern in working_proxies.txt
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for proxy in working:
            f.write(proxy + "\n")

    print(f"\nFinished. Working proxies saved to {OUTPUT_FILE} ({len(working)}/{len(proxies)})")


if __name__ == "__main__":
    main()
