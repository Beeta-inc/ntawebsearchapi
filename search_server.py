import os
import sys
import time
import json
import re
import urllib.parse
from flask import Flask, request, jsonify, send_from_directory, render_template_string

# Local imports
from auth_manager import auth_manager
from cdp_driver import chromium_driver
from direct_scraper import direct_search_engine

app = Flask(__name__, static_folder="static")

START_TIME = time.time()
TOTAL_QUERIES = 0
TOTAL_SERP_QUERIES = 0

def extract_api_key():
    """Extracts API key from Authorization header or query parameter."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()
    if request.headers.get("x-api-key"):
        return request.headers.get("x-api-key").strip()
    if request.args.get("api_key"):
        return request.args.get("api_key").strip()
    return None

def require_auth():
    """Validates API key for protected search and scrape endpoints."""
    # Allow local requests or requests with valid sovereign key
    key = extract_api_key()
    if not key:
        return False
    return auth_manager.validate_key(key)

@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, x-api-key, *"
    return response

# ── 1. Minimal Public Root & Health ──
@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "status": "ready",
        "service": "NTA WebSearch Sovereign API",
        "version": "1.0.0",
        "node": "Lenovo L38012 (Termux aarch64)",
        "docs": "/docs",
        "chromium_sandbox": "active" if chromium_driver.is_alive() else "standby"
    }), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "uptime_sec": int(time.time() - START_TIME),
        "total_queries": TOTAL_QUERIES,
        "serp_queries": TOTAL_SERP_QUERIES,
        "chromium_active": chromium_driver.is_alive(),
        "keys_count": len(auth_manager.list_keys())
    }), 200

# ── 2. Interactive Documentation ──
@app.route("/docs", methods=["GET"])
def docs():
    docs_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs.html")
    if os.path.exists(docs_path):
        return send_from_directory(os.path.dirname(docs_path), "docs.html")
    return jsonify({"message": "API Documentation is located in docs.html"}), 200

# ── 3. 100% SerpAPI Drop-In Endpoint (/search and /search.json) ──
@app.route("/search", methods=["GET", "OPTIONS"])
@app.route("/search.json", methods=["GET", "OPTIONS"])
def serpapi_search():
    if request.method == "OPTIONS":
        return "", 204

    global TOTAL_QUERIES, TOTAL_SERP_QUERIES
    TOTAL_QUERIES += 1
    TOTAL_SERP_QUERIES += 1

    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Missing 'q' query parameter"}), 400

    engine = request.args.get("engine", "google").lower()
    tbs = request.args.get("tbs", "").lower()
    try:
        num = int(request.args.get("num", "10"))
    except ValueError:
        num = 10

    # Optional key enforcement: if keys exist, require valid key
    active_keys = auth_manager.list_keys()
    if len(active_keys) > 0 and not require_auth():
        return jsonify({
            "error": "Unauthorized: Invalid or missing API Key. Pass 'api_key=nta_live_...' or 'Authorization: Bearer <key>'",
            "create_key_url": "https://ntawebsearch.pages.dev/createapi"
        }), 401

    # Route 1: Google Images / Animated GIFs (Replacing _worker.js /api/gifs)
    if engine in ["google_images", "images"]:
        is_animated = "itp:animated" in tbs or "gif" in tbs
        try:
            # Try Real Chromium Sandbox
            if chromium_driver.is_alive():
                return jsonify(chromium_driver.search_google_images(query, num=num, animated_only=is_animated))
        except Exception as e:
            print(f"[SEARCH] Chromium image search failed ({e}), using fallback.", flush=True)

        # Fallback to direct Bing/Google image scraper
        fallback_images = []
        try:
            encoded = urllib.parse.quote_plus(query)
            bing_url = f"https://www.bing.com/images/search?q={encoded}&form=HDRSC2"
            raw_html = direct_search_engine.make_http_request(bing_url, timeout=3.5)
            if raw_html:
                for match in re.finditer(r'murl(?:&quot;|")\s*:\s*(?:&quot;|")(https?:[^&"\n\s]+)', raw_html):
                    img_url = match.group(1).replace("\\/", "/")
                    if img_url.startswith("http") and not "bing.com" in img_url:
                        fallback_images.append({
                            "title": query,
                            "original": img_url,
                            "thumbnail": img_url,
                            "source": "web"
                        })
                    if len(fallback_images) >= num:
                        break
        except Exception:
            pass

        return jsonify({
            "search_metadata": {"status": "Success", "engine": "fallback_image_scraper"},
            "search_parameters": {"q": query, "engine": "google_images"},
            "images_results": fallback_images
        })

    # Route 2: Standard Google Organic Web Search
    # 1. Try Real Headless Chromium Sandbox
    if chromium_driver.ensure_chromium_running():
        try:
            result = chromium_driver.search_google(query, num=num)
            if result.get("organic_results"):
                return jsonify(result)
        except Exception as e:
            print(f"[SEARCH] Chromium search error ({e}), seamlessly falling back to multi-engine.", flush=True)

    # 2. Seamless Fast Multi-Engine Fallback
    fallback_res = direct_search_engine.execute_multi_search(query, num=num)
    return jsonify(fallback_res)

# ── 4. Modern AI Search Endpoint (/api/search) ──
@app.route("/api/search", methods=["GET", "POST", "OPTIONS"])
def ai_search():
    if request.method == "OPTIONS":
        return "", 204

    global TOTAL_QUERIES
    TOTAL_QUERIES += 1

    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        query = data.get("query", "").strip()
        num = data.get("max_sources", 8)
        include_images = data.get("include_images", False)
    else:
        query = request.args.get("q", "").strip()
        num = int(request.args.get("num", "8"))
        include_images = request.args.get("images", "false").lower() == "true"

    if not query:
        return jsonify({"error": "Missing query"}), 400

    active_keys = auth_manager.list_keys()
    if len(active_keys) > 0 and not require_auth():
        return jsonify({"error": "Unauthorized: Invalid API key"}), 401

    start_t = time.time()
    results = []
    engine_used = "multi_engine"

    # Attempt Real Chromium Sandbox first
    if chromium_driver.ensure_chromium_running():
        try:
            res = chromium_driver.search_google(query, num=num)
            results = res.get("organic_results", [])
            engine_used = "real_chromium_sandbox"
        except Exception:
            pass

    # Seamless Fallback if empty
    if not results:
        res = direct_search_engine.execute_multi_search(query, num=num)
        results = res.get("organic_results", [])
        engine_used = "multi_engine_tls_fallback"

    observation_text = direct_search_engine.build_ai_observation(results)
    images = []
    if include_images:
        try:
            img_res = chromium_driver.search_google_images(query, num=4)
            images = img_res.get("images_results", [])
        except Exception:
            pass

    elapsed_ms = int((time.time() - start_t) * 1000)
    return jsonify({
        "success": True,
        "query": query,
        "elapsed_ms": elapsed_ms,
        "engine": engine_used,
        "results": results,
        "images": images,
        "observation": observation_text
    })

# ── 5. Deep Web Page Scraper (/api/scrape) ──
@app.route("/api/scrape", methods=["GET", "POST", "OPTIONS"])
def scrape_endpoint():
    if request.method == "OPTIONS":
        return "", 204

    url = request.args.get("url") or (request.get_json(silent=True) or {}).get("url")
    if not url:
        return jsonify({"error": "Missing 'url' parameter"}), 400

    active_keys = auth_manager.list_keys()
    if len(active_keys) > 0 and not require_auth():
        return jsonify({"error": "Unauthorized"}), 401

    if chromium_driver.ensure_chromium_running():
        try:
            scraped = chromium_driver.render_and_scrape(url)
            return jsonify(scraped)
        except Exception as e:
            print(f"[SCRAPE] Chromium render failed: {e}", flush=True)

    # Static fallback
    raw_html = direct_search_engine.make_http_request(url, timeout=5.0)
    clean_text = direct_search_engine.clean_html(raw_html or "")
    return jsonify({
        "success": bool(raw_html),
        "url": url,
        "title": url,
        "content_text": clean_text[:12000],
        "word_count": len(clean_text.split())
    })

# ── 6. API Key Management (/createapi and /api/keys) ──
@app.route("/createapi", methods=["GET", "POST", "OPTIONS"])
def create_api():
    if request.method == "OPTIONS":
        return "", 204

    name = request.args.get("name") or (request.get_json(silent=True) or {}).get("name") or "NeTuArk App Client"
    raw_key, info = auth_manager.create_key(name=name)

    # Return plaintext raw_key ONLY THIS ONCE!
    return jsonify({
        "success": True,
        "api_key": raw_key,
        "key_id": info["key_id"],
        "name": info["name"],
        "created_at": info["created_at"],
        "warning": "CRITICAL: Save this API Key now! For security, it is stored as a SHA-256 hash and will NEVER be displayed again."
    }), 201

@app.route("/api/keys", methods=["GET"])
def list_api_keys():
    # Only returns safe masked keys (prefix, suffix, usage count)
    return jsonify({
        "success": True,
        "keys": auth_manager.list_keys()
    }), 200

@app.route("/api/keys/revoke", methods=["POST"])
def revoke_api_key():
    data = request.get_json(silent=True) or {}
    key_id = data.get("key_id") or request.args.get("key_id")
    if not key_id:
        return jsonify({"error": "Missing key_id"}), 400
    success = auth_manager.revoke_key(key_id)
    return jsonify({"success": success}), (200 if success else 404)

@app.route("/api/keys/delete", methods=["POST", "DELETE"])
def delete_api_key():
    data = request.get_json(silent=True) or {}
    key_id = data.get("key_id") or request.args.get("key_id")
    if not key_id:
        return jsonify({"error": "Missing key_id"}), 400
    success = auth_manager.delete_key(key_id)
    return jsonify({"success": success}), (200 if success else 404)

if __name__ == "__main__":
    print("[NTA-WEBSEARCH] 🚀 Starting Sovereign Search Server on port 3001...", flush=True)
    # Start Chromium daemon in background thread
    import threading
    threading.Thread(target=chromium_driver.ensure_chromium_running, daemon=True).start()
    app.run(host="0.0.0.0", port=3001, threaded=True)
