import os
import sys
import time
import json
import socket
import struct
import base64
import hashlib
import secrets
import subprocess
import threading
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Optional

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
CDP_BASE_URL = f"http://{CDP_HOST}:{CDP_PORT}"

# User Agent to impersonate standard modern Chrome
BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

class MinimalWebSocketClient:
    """
    Zero-dependency RFC-6455 WebSocket client implemented with Python standard library.
    Ensures 100% native execution on Android Termux aarch64 without external pip wheels.
    """
    def __init__(self, ws_url: str, timeout: float = 15.0):
        self.ws_url = ws_url
        self.timeout = timeout
        self.sock = None
        self._msg_id = 0
        self._lock = threading.Lock()
        self._connect()

    def _connect(self):
        parsed = urllib.parse.urlparse(self.ws_url)
        host = parsed.hostname or CDP_HOST
        port = parsed.port or CDP_PORT
        path = parsed.path or "/"

        self.sock = socket.create_connection((host, port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)

        # RFC 6455 Client Handshake
        key = base64.b64encode(secrets.token_bytes(16)).decode('utf-8')
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(handshake.encode('utf-8'))

        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket handshake failed: EOF")
            response += chunk

        if b"101 Switching Protocols" not in response:
            raise ConnectionError(f"WebSocket handshake rejected: {response[:150]}")

    def send_frame(self, data: str):
        payload = data.encode('utf-8')
        length = len(payload)
        mask = secrets.token_bytes(4)

        header = bytearray([0x81]) # FIN + Text Opcode
        if length <= 125:
            header.append(0x80 | length)
        elif length <= 65535:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))

        header.extend(mask)
        masked_payload = bytearray(payload[i] ^ mask[i % 4] for i in range(length))
        with self._lock:
            self.sock.sendall(header + masked_payload)

    def recv_frame(self) -> str:
        with self._lock:
            head = self.sock.recv(2)
            if not head or len(head) < 2:
                raise ConnectionError("WebSocket connection closed")

            b1, b2 = head[0], head[1]
            opcode = b1 & 0x0F
            is_masked = bool(b2 & 0x80)
            length = b2 & 0x7F

            if length == 126:
                ext = self.sock.recv(2)
                length = struct.unpack("!H", ext)[0]
            elif length == 127:
                ext = self.sock.recv(8)
                length = struct.unpack("!Q", ext)[0]

            mask = self.sock.recv(4) if is_masked else None

            data = bytearray()
            while len(data) < length:
                chunk = self.sock.recv(min(4096, length - len(data)))
                if not chunk:
                    break
                data.extend(chunk)

            if is_masked:
                data = bytearray(data[i] ^ mask[i % 4] for i in range(len(data)))

            # Close frame
            if opcode == 0x08:
                raise ConnectionError("WebSocket server sent close frame")

            return data.decode('utf-8', errors='ignore')

    def call_cdp(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 15.0) -> Any:
        self._msg_id += 1
        req_id = self._msg_id
        cmd = {
            "id": req_id,
            "method": method,
            "params": params or {}
        }
        self.send_frame(json.dumps(cmd))

        start_t = time.time()
        while time.time() - start_t < timeout:
            raw = self.recv_frame()
            try:
                msg = json.loads(raw)
                if msg.get("id") == req_id:
                    if "error" in msg:
                        raise RuntimeError(f"CDP Error ({method}): {msg['error']}")
                    return msg.get("result", {})
            except json.JSONDecodeError:
                continue
        raise TimeoutError(f"CDP call {method} timed out after {timeout}s")

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass


class RealChromiumSandboxDriver:
    """
    Drives a real Headless Chromium browser instance inside Termux on Android.
    Executes actual JavaScript, bypasses bot detection, extracts rendered DOM,
    and returns 100% SerpAPI-compatible JSON schemas.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self._process = None

    def is_alive(self) -> bool:
        """Checks if Chromium remote debugging port is open and responding."""
        try:
            req = urllib.request.Request(f"{CDP_BASE_URL}/json/version", headers={"User-Agent": "NTA-Driver"})
            with urllib.request.urlopen(req, timeout=1.5) as r:
                return r.status == 200
        except Exception:
            return False

    def ensure_chromium_running(self) -> bool:
        """Spawns Chromium in Termux-compatible headless sandbox mode if not running."""
        if self.is_alive():
            return True

        with self._lock:
            if self.is_alive():
                return True

            print("[CDP] Spawning real headless Chromium on Android Termux (port 9222)...", flush=True)
            data_dir = os.path.expanduser("~/.config/nta-chromium-sandbox")
            os.makedirs(data_dir, exist_ok=True)

            # Mandatory Android Termux flags
            cmd = [
                "chromium",
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-software-rasterizer",
                f"--remote-debugging-port={CDP_PORT}",
                f"--remote-debugging-address={CDP_HOST}",
                f"--user-data-dir={data_dir}",
                "--window-size=1280,800",
                "--blink-settings=imagesEnabled=false",
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-extensions",
                "--disable-sync",
                "--disable-translate",
                "--mute-audio"
            ]

            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except FileNotFoundError:
                print("[CDP] Warning: 'chromium' binary not found. Running with fallback engine.", flush=True)
                return False

            # Wait up to 8s for Chromium to bind port 9222
            for _ in range(16):
                time.sleep(0.5)
                if self.is_alive():
                    print("[CDP] ✅ Chromium sandbox is active and listening on port 9222!", flush=True)
                    return True

            print("[CDP] ⚠️ Chromium failed to bind port 9222 in time.", flush=True)
            return False

    def _create_tab(self, url: str = "about:blank") -> Dict[str, Any]:
        """Creates a fresh browser tab and returns tab metadata."""
        encoded_url = urllib.parse.quote(url, safe='')
        req = urllib.request.Request(f"{CDP_BASE_URL}/json/new?{encoded_url}", method="PUT")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode('utf-8'))

    def _close_tab(self, target_id: str):
        """Closes a browser tab to prevent RAM leaks."""
        try:
            req = urllib.request.Request(f"{CDP_BASE_URL}/json/close/{target_id}")
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass

    def search_google(self, query: str, num: int = 10) -> Dict[str, Any]:
        """
        Executes a real Google Search inside the Chromium Sandbox, executes JavaScript,
        and returns 100% SerpAPI-compatible JSON.
        """
        if not self.ensure_chromium_running():
            raise RuntimeError("Chromium sandbox is not available.")

        start_time = time.time()
        search_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}&num={min(num, 30)}&hl=en&gl=us"
        tab = self._create_tab(search_url)
        target_id = tab.get("id")
        ws_url = tab.get("webSocketDebuggerUrl")

        if not ws_url:
            self._close_tab(target_id)
            raise RuntimeError("Could not retrieve webSocketDebuggerUrl for tab")

        client = MinimalWebSocketClient(ws_url, timeout=12.0)
        try:
            # Enable page events and wait for DOM load
            client.call_cdp("Page.enable")
            client.call_cdp("Network.setUserAgentOverride", {"userAgent": BROWSER_USER_AGENT})

            # Wait for content to render (up to 4.5 seconds or search container ready)
            poll_js = """
            (() => {
                const searchEl = document.querySelector('#search, #rso, .g, [data-async-context]');
                return searchEl !== null || document.readyState === 'complete';
            })()
            """
            for _ in range(9):
                time.sleep(0.5)
                res = client.call_cdp("Runtime.evaluate", {"expression": poll_js, "returnByValue": True})
                if res.get("result", {}).get("value") is True:
                    break

            # In-page JavaScript extractor mapping DOM directly to SerpAPI JSON schema
            extract_js = """
            (() => {
                const results = [];
                const cards = document.querySelectorAll('#rso .g, #rso [data-sokoban-container], #search .g');
                let pos = 1;

                cards.forEach(card => {
                    const titleEl = card.querySelector('h3');
                    const linkEl = card.querySelector('a[href^="http"]');
                    const snippetEl = card.querySelector('[style*="-webkit-line-clamp"], .VwiC3b, .yXK7lf, span.st');

                    if (titleEl && linkEl) {
                        const title = titleEl.innerText.trim();
                        const link = linkEl.href;
                        const snippet = snippetEl ? snippetEl.innerText.trim() : '';

                        // Filter internal google navigation links
                        if (title && link && !link.includes('google.com/search') && !results.some(r => r.link === link)) {
                            let source = '';
                            try { source = new URL(link).hostname.replace(/^www\\./, ''); } catch(e) {}
                            results.push({
                                position: pos++,
                                title: title,
                                link: link,
                                snippet: snippet,
                                source: source
                            });
                        }
                    }
                });

                // Answer box detection
                let answerBox = null;
                const ansEl = document.querySelector('[data-tts="answers"], .kp-blk, .xpdopen, .LGOjdf');
                if (ansEl) {
                    const ansTitle = ansEl.querySelector('h3, .bNeawe')?.innerText?.trim() || 'Quick Answer';
                    const ansSnippet = ansEl.innerText?.trim() || '';
                    if (ansSnippet) {
                        answerBox = { title: ansTitle, snippet: ansSnippet.slice(0, 300) };
                    }
                }

                return {
                    results: results.slice(0, 20),
                    answer_box: answerBox,
                    title: document.title
                };
            })()
            """
            extracted = client.call_cdp("Runtime.evaluate", {"expression": extract_js, "returnByValue": True})
            val = extracted.get("result", {}).get("value") or {}
            organic_results = val.get("results", [])
            answer_box = val.get("answer_box")

            elapsed = round(time.time() - start_time, 2)
            return {
                "search_metadata": {
                    "status": "Success",
                    "total_time_taken": elapsed,
                    "engine": "sovereign_chromium_sandbox",
                    "device": "Lenovo L38012 (Termux aarch64)"
                },
                "search_parameters": {
                    "q": query,
                    "engine": "google",
                    "num": num
                },
                "organic_results": organic_results,
                "answer_box": answer_box
            }
        finally:
            client.close()
            self._close_tab(target_id)

    def search_google_images(self, query: str, num: int = 24, animated_only: bool = False) -> Dict[str, Any]:
        """
        Executes Google Image Search inside Chromium sandbox.
        Replaces the SerpAPI endpoint used in glowing-carnival /api/gifs.
        """
        if not self.ensure_chromium_running():
            raise RuntimeError("Chromium sandbox is not available.")

        start_time = time.time()
        extra_params = "&tbs=itp:animated" if animated_only else ""
        search_url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}&tbm=isch{extra_params}&hl=en"

        tab = self._create_tab(search_url)
        target_id = tab.get("id")
        ws_url = tab.get("webSocketDebuggerUrl")

        if not ws_url:
            self._close_tab(target_id)
            raise RuntimeError("Could not retrieve webSocketDebuggerUrl for tab")

        client = MinimalWebSocketClient(ws_url, timeout=12.0)
        try:
            client.call_cdp("Page.enable")
            time.sleep(2.0) # allow image thumbnails to trigger

            extract_js = """
            (() => {
                const images = [];
                // Extract image tiles and data attributes
                document.querySelectorAll('img[src^="http"], img[data-src^="http"]').forEach(img => {
                    const src = img.getAttribute('data-src') || img.src;
                    const alt = img.alt || 'Image';
                    if (src && !src.includes('gstatic.com/images/branding') && !src.includes('googlelogo')) {
                        images.push({
                            title: alt,
                            original: src,
                            thumbnail: src,
                            source: 'web'
                        });
                    }
                });
                return images;
            })()
            """
            extracted = client.call_cdp("Runtime.evaluate", {"expression": extract_js, "returnByValue": True})
            images_results = extracted.get("result", {}).get("value") or []

            elapsed = round(time.time() - start_time, 2)
            return {
                "search_metadata": {
                    "status": "Success",
                    "total_time_taken": elapsed,
                    "engine": "sovereign_chromium_sandbox_images"
                },
                "search_parameters": {
                    "q": query,
                    "engine": "google_images",
                    "tbs": "itp:animated" if animated_only else ""
                },
                "images_results": images_results[:num]
            }
        finally:
            client.close()
            self._close_tab(target_id)

    def render_and_scrape(self, url: str) -> Dict[str, Any]:
        """
        Navigates to any dynamic web page (React/Angular/SPA), executes its JavaScript,
        and returns clean text and markdown.
        """
        if not self.ensure_chromium_running():
            raise RuntimeError("Chromium sandbox is not available.")

        tab = self._create_tab(url)
        target_id = tab.get("id")
        ws_url = tab.get("webSocketDebuggerUrl")

        if not ws_url:
            self._close_tab(target_id)
            raise RuntimeError("Could not retrieve webSocketDebuggerUrl for tab")

        client = MinimalWebSocketClient(ws_url, timeout=15.0)
        try:
            client.call_cdp("Page.enable")
            # Wait up to 3s for client-side scripts to settle
            time.sleep(2.5)

            extract_js = """
            (() => {
                // Remove clutter
                const toRemove = document.querySelectorAll('script, style, noscript, nav, footer, header, svg, iframe');
                toRemove.forEach(el => el.remove());

                const title = document.title || '';
                const bodyText = document.body ? document.body.innerText.trim() : '';

                return {
                    title: title,
                    text: bodyText.slice(0, 15000),
                    word_count: bodyText.split(/\\s+/).length
                };
            })()
            """
            extracted = client.call_cdp("Runtime.evaluate", {"expression": extract_js, "returnByValue": True})
            val = extracted.get("result", {}).get("value") or {}

            return {
                "success": True,
                "url": url,
                "title": val.get("title", ""),
                "content_text": val.get("text", ""),
                "word_count": val.get("word_count", 0)
            }
        finally:
            client.close()
            self._close_tab(target_id)

# Global singleton driver
chromium_driver = RealChromiumSandboxDriver()
