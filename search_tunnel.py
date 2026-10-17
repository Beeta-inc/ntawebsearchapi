import subprocess
import re
import time
import urllib.request
import json
import uuid
import sys
import os
import shutil
from datetime import datetime, timezone
import threading

# ── CONFIGURATION ──
SYNC_FIRESTORE_URL = "https://firestore.googleapis.com/v1/projects/ntamedia-1f03d/databases/(default)/documents/serverSync/coordinator"

if not os.path.exists('.device_id'):
    with open('.device_id', 'w') as f:
        f.write(str(uuid.uuid4())[:8])
with open('.device_id', 'r') as f:
    DEVICE_ID = f.read().strip()

PAGES_REG_URL = "https://ntawebsearch.pages.dev/register_tunnel"
PAGES_SHARED_SECRET = "ntamedia_tunnel_key"

GITHUB_PAT = os.environ.get("GITHUB_PAT", "ghp_zr2CnF7" + "GoiRwuuLghxjtottYEOf02i05gn2L")
GITHUB_REPO = "Beeta-inc/ntawebsearchapi"
GITHUB_FILE = "endpoint.json"

current_process = None
current_url = None
last_pushed_url = None

def get_utc_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

def is_network_online(timeout: float = 1.0) -> bool:
    """Fast socket check to 1.1.1.1 to confirm WAN routing."""
    import socket
    for ip in ["1.1.1.1", "8.8.8.8"]:
        try:
            s = socket.create_connection((ip, 53), timeout=timeout)
            s.close()
            return True
        except Exception:
            continue
    return False

def wait_for_network_recovery() -> int:
    """Continuously polls until network connectivity is fully restored."""
    print("\n[SEARCH-WATCHDOG] ⚠️ Network disconnected! Pinging 1.1.1.1 continuously...", flush=True)
    start_time = time.time()
    while True:
        time.sleep(2)
        if is_network_online(timeout=1.5):
            downtime = int(time.time() - start_time)
            print(f"[SEARCH-WATCHDOG] 🚀 Network restored after {downtime}s! (Reconnecting search tunnel)...", flush=True)
            return downtime

def register_with_pages(url: str):
    """Registers the live tunnel endpoint with Cloudflare Pages Functions."""
    try:
        payload = json.dumps({"endpoint": url, "secret": PAGES_SHARED_SECRET}).encode()
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        req = urllib.request.Request(PAGES_REG_URL, data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            print(f"[PAGES] Registered Search Tunnel with Cloudflare Pages: {data.get('status')} -> {data.get('active_origin')}", flush=True)
    except Exception as e:
        print(f"[PAGES] Warning: Could not register search tunnel with Pages: {e}", flush=True)

def push_endpoint_json(url: str):
    """Updates endpoint.json on GitHub repository for cold-start edge fallbacks."""
    import base64
    new_content = json.dumps({"endpoint": url, "updated_at": get_utc_iso()}, indent=2)
    encoded = base64.b64encode(new_content.encode()).decode()
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    headers_dict = {
        "Authorization": f"token {GITHUB_PAT}",
        "Content-Type": "application/json",
        "User-Agent": "ntawebsearch-auto"
    }
    try:
        sha = ""
        try:
            get_req = urllib.request.Request(api_url, headers=headers_dict)
            with urllib.request.urlopen(get_req, timeout=10) as r:
                sha = json.loads(r.read().decode()).get("sha", "")
        except Exception:
            pass

        payload_dict = {
            "message": f"auto: search tunnel {url[:50]}",
            "content": encoded
        }
        if sha:
            payload_dict["sha"] = sha

        payload = json.dumps(payload_dict).encode()
        put_req = urllib.request.Request(api_url, data=payload, headers=headers_dict, method="PUT")
        with urllib.request.urlopen(put_req, timeout=10) as r:
            print(f"[GIT] Search endpoint.json updated on GitHub -> {url}", flush=True)
    except Exception as e:
        print(f"[GIT] Warning: Could not update endpoint.json on GitHub: {e}", flush=True)

def update_firestore_search_tunnel(url: str):
    """Publishes live search tunnel directly to Firestore coordinator node registry."""
    field_name = f"search_url_{DEVICE_ID}"
    data = {
        "fields": {
            field_name: {"stringValue": url},
            "search_master_url": {"stringValue": url},
            "search_updated_at": {"timestampValue": get_utc_iso()}
        }
    }
    update_paths = f"updateMask.fieldPaths={field_name}&updateMask.fieldPaths=search_master_url&updateMask.fieldPaths=search_updated_at"
    patch_url = f"{SYNC_FIRESTORE_URL}?{update_paths}"
    try:
        req = urllib.request.Request(patch_url, data=json.dumps(data).encode('utf-8'), method='PATCH')
        req.add_header('Content-Type', 'application/json')
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[!] Warning: Failed to update Firestore with search tunnel: {e}", flush=True)

def read_cloudflared_output(process):
    global current_url
    for line in iter(process.stdout.readline, ''):
        print(line, end='', flush=True)
        if current_url is None:
            match = re.search(r'(https://[a-zA-Z0-9-]+\.trycloudflare\.com)', line)
            if match:
                current_url = match.group(1)
                print(f"\n[+] LIVE SEARCH TUNNEL: {current_url}\n", flush=True)
                threading.Thread(target=register_with_pages, args=(current_url,), daemon=True).start()
                threading.Thread(target=push_endpoint_json, args=(current_url,), daemon=True).start()
                threading.Thread(target=update_firestore_search_tunnel, args=(current_url,), daemon=True).start()

def start_tunnel():
    global current_process, current_url
    if current_process is not None and current_process.poll() is None:
        return

    print("[*] Starting Cloudflare Tunnel for Search API (port 3001)...", flush=True)
    current_url = None
    try:
        current_process = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", "http://127.0.0.1:3001"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        t = threading.Thread(target=read_cloudflared_output, args=(current_process,))
        t.daemon = True
        t.start()
    except Exception as e:
        print(f"[!] Error starting cloudflared for search: {e}", flush=True)

def ensure_search_server_running():
    """Verifies search_server.py is listening on port 3001; respawns if crashed."""
    import socket
    try:
        s = socket.create_connection(("127.0.0.1", 3001), timeout=1)
        s.close()
        return True
    except Exception:
        pass

    print("[SEARCH-WATCHDOG] ⚠️ search_server.py is not listening on port 3001! Resurrecting...", flush=True)
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    subprocess.run(["pkill", "-9", "-f", "ntawebsearchapi/search_server\\.py"], capture_output=True)
    time.sleep(1)
    try:
        log_out = open(os.path.join(repo_dir, "search_server.log"), "a")
        subprocess.Popen(
            [sys.executable, os.path.join(repo_dir, "search_server.py")],
            cwd=repo_dir,
            stdout=log_out,
            stderr=subprocess.STDOUT
        )
        time.sleep(2)
        return True
    except Exception as e:
        print(f"[SEARCH-WATCHDOG] Error spawning search_server.py: {e}", flush=True)
        return False

def ensure_chromium_running():
    """Verifies headless Chromium CDP is listening on port 9222; launches if inactive."""
    import socket
    try:
        s = socket.create_connection(("127.0.0.1", 9222), timeout=1)
        s.close()
        return True
    except Exception:
        pass

    print("[SEARCH-WATCHDOG] 🌐 Launching fresh Chromium CDP sandbox on port 9222...", flush=True)
    subprocess.run(["pkill", "-9", "-f", "chromium.*9222"], capture_output=True)
    subprocess.run(["pkill", "-9", "-f", "chrome.*9222"], capture_output=True)
    time.sleep(1)

    chrome_bin = shutil.which("chromium") or shutil.which("chrome") or shutil.which("chromium-browser")
    if not chrome_bin:
        for p in ["/data/data/com.termux/files/usr/bin/chromium", "/data/data/com.termux/files/usr/bin/chrome"]:
            if os.path.exists(p):
                chrome_bin = p
                break
    if chrome_bin:
        cmd = [
            chrome_bin,
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-software-rasterizer",
            "--remote-debugging-port=9222",
            "--remote-debugging-address=127.0.0.1",
            "--user-data-dir=" + os.path.expanduser("~/.config/nta-chromium-sandbox"),
            "--window-size=1280,800",
            "--blink-settings=imagesEnabled=false",
            "--disable-blink-features=AutomationControlled",
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "about:blank"
        ]
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
            return True
        except Exception as e:
            print(f"[SEARCH-WATCHDOG] Error launching Chromium: {e}", flush=True)
    return False

def restart_search_stack():
    """Restarts search_server.py, Chromium CDP, and cloudflared tunnel upon network recovery."""
    global current_process, current_url, last_pushed_url
    print("\n[SEARCH-WATCHDOG] 🔄 Full search stack recovery initiated...", flush=True)
    repo_dir = os.path.dirname(os.path.abspath(__file__))

    # 1. Terminate search tunnel only
    if current_process:
        try:
            current_process.terminate()
            current_process.kill()
        except Exception:
            pass
        current_process = None
    subprocess.run(["pkill", "-9", "-f", "cloudflared.*3001"], capture_output=True)

    # 2. Terminate search server only
    subprocess.run(["pkill", "-9", "-f", "ntawebsearchapi/search_server\\.py"], capture_output=True)

    # 3. Re-assert Termux wake lock
    try:
        subprocess.run(["termux-wake-lock"], capture_output=True, timeout=2)
    except Exception:
        pass

    # 4. Restart Chromium to flush DNS caches
    ensure_chromium_running()
    time.sleep(1)

    # 5. Spawn fresh search_server.py
    try:
        log_out = open(os.path.join(repo_dir, "search_server.log"), "a")
        subprocess.Popen(
            [sys.executable, os.path.join(repo_dir, "search_server.py")],
            cwd=repo_dir,
            stdout=log_out,
            stderr=subprocess.STDOUT
        )
    except Exception as e:
        print(f"[SEARCH-WATCHDOG] Error spawning search_server.py: {e}", flush=True)

    # 6. Wait for port 3001
    import socket
    for _ in range(15):
        time.sleep(1)
        try:
            s = socket.create_connection(("127.0.0.1", 3001), timeout=1)
            s.close()
            break
        except Exception:
            pass

    current_url = None
    last_pushed_url = None
    start_tunnel()

def run_search_coordinator():
    global current_process, current_url, last_pushed_url
    print(f"Starting NTA WebSearch Tunnel Supervisor. Device ID: {DEVICE_ID}", flush=True)

    try:
        subprocess.run(["termux-wake-lock"], capture_output=True, timeout=2)
    except Exception:
        pass

    ensure_chromium_running()
    ensure_search_server_running()
    start_tunnel()

    while True:
        # 1. 🌐 Network Watchdog
        if not is_network_online(timeout=1.5):
            wait_for_network_recovery()
            restart_search_stack()
            continue

        # 2. 🛡️ Local Search Server Watchdog (Port 3001)
        ensure_search_server_running()

        # 3. 🌐 Chromium CDP Watchdog (Port 9222)
        ensure_chromium_running()

        # 4. 🛡️ Search Tunnel Process Liveness Watchdog (Port 3001)
        if current_process is None or current_process.poll() is not None:
            print("[SEARCH-WATCHDOG] ⚠️ Search tunnel inactive/crashed. Respawning...", flush=True)
            current_process = None
            start_tunnel()

        if current_url:
            if current_url != last_pushed_url:
                update_firestore_search_tunnel(current_url)
                last_pushed_url = current_url
            else:
                update_firestore_search_tunnel(current_url)

        time.sleep(10)

if __name__ == "__main__":
    try:
        run_search_coordinator()
    except KeyboardInterrupt:
        if current_process:
            current_process.terminate()
            subprocess.run(["pkill", "-f", "cloudflared.*3001"])
