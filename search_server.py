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
from extended_engines import (
    RedditEngine,
    GitHubEngine,
    AmazonEngine,
    YouTubeEngine,
    LinkedInJobsEngine,
    PlacesEngine,
    MathAndUnitsEngine
)
from youtube_reader import YouTubeReader

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
    if request.is_json:
        data = request.get_json(silent=True) or {}
        if data.get("api_key"):
            return str(data.get("api_key")).strip()
    return None

def require_auth():
    """Validates API key for protected search and scrape endpoints."""
    # Allow loopback and local internal cluster mesh requests without API key
    if request.remote_addr in ["127.0.0.1", "::1", "localhost"] and not request.headers.get("cf-connecting-ip"):
        return True
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
@app.route("/status", methods=["GET"])
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

    query = request.args.get("q", "").strip() or request.args.get("v", "").strip() or request.args.get("video_id", "").strip() or request.args.get("url", "").strip()
    if not query:
        return jsonify({"error": "Missing 'q', 'v', or 'url' query parameter"}), 400

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

    # Check Calculator / Unit Converter first
    math_box = MathAndUnitsEngine.evaluate(query)
    # If pure calculation or unit conversion without broader web keywords, return instantly
    if math_box and (math_box.get("type") == "unit_converter" or not re.search(r"[a-zA-Z]{5,}", query)):
        return jsonify({
            "search_metadata": {
                "status": "Success",
                "engine": "sovereign_math_calculator",
                "total_time_taken": 0.001,
                "device": "Lenovo L38012 (Termux aarch64)"
            },
            "search_parameters": {"q": query, "engine": engine},
            "answer_box": math_box,
            "organic_results": [{
                "position": 1,
                "title": math_box.get("title", "Calculation Result"),
                "answer": math_box.get("answer"),
                "snippet": math_box.get("formula") or math_box.get("answer")
            }]
        })

    # Route: Reddit Search Engine
    if engine in ["reddit", "r"]:
        sub = request.args.get("subreddit")
        sort = request.args.get("sort", "relevance")
        t_filter = request.args.get("time", "all")
        return jsonify(RedditEngine.search(query, subreddit=sub, sort=sort, time_filter=t_filter, limit=num))

    # Route: GitHub Repository Search Engine
    if engine in ["github", "gh", "github_repos"]:
        sort = request.args.get("sort", "stars")
        return jsonify(GitHubEngine.search_repositories(query, limit=num, sort=sort))

    # Route: YouTube Video & Live Stream Search Engine
    if engine in ["youtube", "yt", "videos"]:
        live_only = request.args.get("live", "false").lower() == "true"
        return jsonify(YouTubeEngine.search_videos(query, limit=num, live_only=live_only))

    # Route: YouTube Video Content & Transcript Reader
    if engine in ["youtube_read", "yt_read", "read_video", "video_read"]:
        v_id = request.args.get("v") or request.args.get("video_id") or query
        lang = request.args.get("lang", "en")
        force_stt = request.args.get("force_stt", "false").lower() == "true"
        return jsonify(YouTubeReader.read_video(v_id, lang=lang, force_stt=force_stt))

    # Route: LinkedIn Public Guest Jobs Search Engine
    if engine in ["linkedin_jobs", "jobs", "linkedin"]:
        location = request.args.get("location")
        return jsonify(LinkedInJobsEngine.search_jobs(query, location=location, limit=num))

    # Route: Maps & Local Places Geocoding Engine
    if engine in ["places", "maps", "local"]:
        return jsonify(PlacesEngine.search_places(query, limit=num))

    # Route: Amazon Autocomplete / Product Suggestions
    if engine in ["amazon_autocomplete", "amazon"]:
        country = request.args.get("country", "us")
        return jsonify(AmazonEngine.autocomplete(query, country=country))

    # Route: Google Images / Animated GIFs
    if engine in ["google_images", "images"]:
        is_animated = "itp:animated" in tbs or "gif" in tbs
        try:
            if chromium_driver.is_alive():
                return jsonify(chromium_driver.search_google_images(query, num=num, animated_only=is_animated))
        except Exception as e:
            print(f"[SEARCH] Chromium image search failed ({e}), using fallback.", flush=True)

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

    # Route: Standard Organic Web Search (Google / Multi-Engine)
    # 1. Try Real Headless Chromium Sandbox
    result = None
    if chromium_driver.ensure_chromium_running():
        try:
            result = chromium_driver.search_google(query, num=num, engine=engine)
            if not result.get("organic_results"):
                result = None
        except Exception as e:
            print(f"[SEARCH] Chromium search error ({e}), seamlessly falling back to multi-engine.", flush=True)
            result = None

    # 2. Seamless Fast Multi-Engine Fallback
    if not result:
        result = direct_search_engine.execute_multi_search(query, num=num)

    # Attach calculator answer box if detected on web query
    if math_box and not result.get("answer_box"):
        result["answer_box"] = math_box

    return jsonify(result)

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

    # 1. Calculator / Math check
    math_box = MathAndUnitsEngine.evaluate(query)

    # 2. Domain intent routing for AI search
    q_lower = query.lower()
    extra_observation_sections = []

    # If user explicitly asks for Reddit
    if "reddit" in q_lower:
        try:
            reddit_data = RedditEngine.search(query, limit=5)
            r_posts = reddit_data.get("reddit_results", [])
            if r_posts:
                r_lines = ["\n=== REDDIT COMMUNITY DISCUSSIONS & USER THREADS ==="]
                for p in r_posts:
                    r_lines.append(f"• [{p.get('subreddit', 'r/reddit')}] {p['title']}")
                    r_lines.append(f"  URL: {p['link']}")
                    if p.get("snippet"):
                        r_lines.append(f"  Extract: {p['snippet']}")
                extra_observation_sections.append("\n".join(r_lines))
        except Exception:
            pass

    # If user explicitly asks for GitHub
    if "github" in q_lower:
        try:
            gh_data = GitHubEngine.search_repositories(query, limit=4)
            gh_repos = gh_data.get("github_results", [])
            if gh_repos:
                gh_lines = ["\n=== GITHUB OPEN-SOURCE REPOSITORIES ==="]
                for g in gh_repos:
                    gh_lines.append(f"• {g['title']} [⭐ {g['stars']} stars, {g['language'] or 'Tech'}]")
                    gh_lines.append(f"  URL: {g['link']}")
                    if g.get("description"):
                        gh_lines.append(f"  Description: {g['description']}")
                extra_observation_sections.append("\n".join(gh_lines))
        except Exception:
            pass

    # If user explicitly asks for Jobs
    if re.search(r"\b(?:jobs?|hiring|careers?)\b", q_lower):
        try:
            job_data = LinkedInJobsEngine.search_jobs(query, limit=4)
            j_list = job_data.get("jobs_results", [])
            if j_list:
                j_lines = ["\n=== VERIFIED CAREER OPPORTUNITIES & JOB OPENINGS ==="]
                for j in j_list:
                    j_lines.append(f"• {j['title']} at {j['company']} ({j['location']})")
                    j_lines.append(f"  Application Link: {j['link']}")
                extra_observation_sections.append("\n".join(j_lines))
        except Exception:
            pass

    # Attempt Real Chromium Sandbox first
    res = None
    if chromium_driver.ensure_chromium_running():
        try:
            res = chromium_driver.search_google(query, num=num)
            results = res.get("organic_results", [])
            if results:
                engine_used = "real_chromium_sandbox"
            else:
                res = None
        except Exception:
            res = None

    # Seamless Fallback if empty
    if not results or not res:
        res = direct_search_engine.execute_multi_search(query, num=num)
        results = res.get("organic_results", [])
        engine_used = "multi_engine_tls_fallback"

    base_obs = (res or {}).get("observation") or direct_search_engine.build_ai_observation(
        organic_results=results,
        answer_box=(res or {}).get("answer_box") or math_box,
        knowledge_graph=(res or {}).get("knowledge_graph"),
        top_stories=(res or {}).get("top_stories"),
        query=query
    )

    # Prepend math answer if available
    obs_parts = []
    if math_box:
        obs_parts.append(f"=== DIRECT CALCULATOR / UNIT CONVERSION ANSWER ===\nResult: {math_box.get('answer')}\nFormula: {math_box.get('formula') or math_box.get('latex') or ''}\n")
    obs_parts.append(base_obs)
    if extra_observation_sections:
        obs_parts.extend(extra_observation_sections)

    final_observation = "\n".join(obs_parts)

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
        "answer_box": math_box or (res or {}).get("answer_box"),
        "results": results,
        "images": images,
        "observation": final_observation
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
    links = []
    if raw_html:
        for a_match in re.finditer(r'<a\s+[^>]*href=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>', raw_html, re.IGNORECASE):
            u = a_match.group(1)
            t = direct_search_engine.clean_html(a_match.group(2))
            if t and len(t) > 10 and not any(l["url"] == u for l in links):
                links.append({"title": t[:100], "url": u})
                if len(links) >= 30:
                    break

    return jsonify({
        "success": bool(raw_html),
        "url": url,
        "title": url,
        "content_text": clean_text[:12000],
        "text": clean_text[:12000],
        "word_count": len(clean_text.split()),
        "links": links,
        "headlines": [l["title"] for l in links if len(l["title"]) > 15]
    })

# ── 6. API Key Management (/createapi and /api/keys) ──
@app.route("/createapi", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/keys/create", methods=["GET", "POST", "OPTIONS"])
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
@app.route("/api/keys/list", methods=["GET"])
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
# ── 7. Sovereign Domain Endpoints (Reddit, GitHub, Amazon, YouTube, LinkedIn, Places, Calc) ──

@app.route("/api/reddit/search", methods=["GET", "POST", "OPTIONS"])
def api_reddit_search():
    if request.method == "OPTIONS": return "", 204
    active_keys = auth_manager.list_keys()
    if len(active_keys) > 0 and not require_auth():
        return jsonify({"error": "Unauthorized"}), 401

    q = request.args.get("q") or (request.get_json(silent=True) or {}).get("q", "")
    if not q: return jsonify({"error": "Missing 'q' query parameter"}), 400
    sub = request.args.get("subreddit")
    sort = request.args.get("sort", "relevance")
    t_filter = request.args.get("time", "all")
    limit = int(request.args.get("limit", "10"))
    return jsonify(RedditEngine.search(q, subreddit=sub, sort=sort, time_filter=t_filter, limit=limit))

@app.route("/api/github/profile", methods=["GET", "OPTIONS"])
def api_github_profile():
    if request.method == "OPTIONS": return "", 204
    user = request.args.get("user") or request.args.get("username", "")
    if not user: return jsonify({"error": "Missing 'user' query parameter"}), 400
    res = GitHubEngine.get_profile(user)
    return jsonify(res), (res.get("status", 200) if isinstance(res.get("status"), int) else 200)

@app.route("/api/github/repo", methods=["GET", "OPTIONS"])
def api_github_repo():
    if request.method == "OPTIONS": return "", 204
    repo_param = request.args.get("repo", "")
    owner = request.args.get("owner", "")
    if "/" in repo_param:
        parts = repo_param.strip().split("/", 1)
        owner, repo_name = parts[0], parts[1]
    else:
        repo_name = repo_param

    if not owner or not repo_name:
        return jsonify({"error": "Missing 'owner' and 'repo' parameter (e.g. repo=torvalds/linux)"}), 400
    res = GitHubEngine.get_repository(owner, repo_name)
    return jsonify(res), (res.get("status", 200) if isinstance(res.get("status"), int) else 200)

@app.route("/api/github/trending", methods=["GET", "OPTIONS"])
def api_github_trending():
    if request.method == "OPTIONS": return "", 204
    lang = request.args.get("language")
    since = request.args.get("since", "daily")
    return jsonify(GitHubEngine.get_trending(language=lang, since=since))

@app.route("/api/amazon/autocomplete", methods=["GET", "OPTIONS"])
def api_amazon_autocomplete():
    if request.method == "OPTIONS": return "", 204
    q = request.args.get("q") or request.args.get("prefix", "")
    if not q: return jsonify({"error": "Missing 'q' query parameter"}), 400
    country = request.args.get("country", "us")
    return jsonify(AmazonEngine.autocomplete(q, country=country))

@app.route("/api/youtube/search", methods=["GET", "POST", "OPTIONS"])
def api_youtube_search():
    if request.method == "OPTIONS": return "", 204
    q = request.args.get("q") or (request.get_json(silent=True) or {}).get("q", "")
    if not q: return jsonify({"error": "Missing 'q' query parameter"}), 400
    live_only = request.args.get("live", "false").lower() == "true"
    limit = int(request.args.get("limit", "10"))
    return jsonify(YouTubeEngine.search_videos(q, limit=limit, live_only=live_only))

@app.route("/api/youtube/read", methods=["GET", "POST", "OPTIONS"])
def api_youtube_read():
    if request.method == "OPTIONS": return "", 204
    active_keys = auth_manager.list_keys()
    if len(active_keys) > 0 and not require_auth():
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    v_param = request.args.get("v") or request.args.get("video_id") or request.args.get("url") or data.get("v") or data.get("video_id") or data.get("url") or request.args.get("q", "")
    if not v_param:
        return jsonify({"error": "Missing 'v', 'video_id', or 'url' parameter"}), 400

    lang = request.args.get("lang") or data.get("lang") or "en"
    force_stt = (str(request.args.get("force_stt", "false")).lower() == "true") or bool(data.get("force_stt", False))
    return jsonify(YouTubeReader.read_video(v_param, lang=lang, force_stt=force_stt))

@app.route("/api/linkedin/jobs", methods=["GET", "POST", "OPTIONS"])
def api_linkedin_jobs():
    if request.method == "OPTIONS": return "", 204
    keywords = request.args.get("keywords") or request.args.get("q") or (request.get_json(silent=True) or {}).get("keywords", "")
    if not keywords: return jsonify({"error": "Missing 'keywords' parameter"}), 400
    location = request.args.get("location")
    limit = int(request.args.get("limit", "10"))
    return jsonify(LinkedInJobsEngine.search_jobs(keywords, location=location, limit=limit))

@app.route("/api/places/search", methods=["GET", "OPTIONS"])
def api_places_search():
    if request.method == "OPTIONS": return "", 204
    q = request.args.get("q") or request.args.get("place", "")
    if not q: return jsonify({"error": "Missing 'q' query parameter"}), 400
    limit = int(request.args.get("limit", "10"))
    return jsonify(PlacesEngine.search_places(q, limit=limit))

@app.route("/api/calc", methods=["GET", "POST", "OPTIONS"])
@app.route("/api/math", methods=["GET", "POST", "OPTIONS"])
def api_calc():
    if request.method == "OPTIONS": return "", 204
    expr = request.args.get("q") or request.args.get("expr") or (request.get_json(silent=True) or {}).get("expr", "")
    if not expr: return jsonify({"error": "Missing 'q' or 'expr' parameter"}), 400
    res = MathAndUnitsEngine.evaluate(expr)
    if res:
        return jsonify({"success": True, "answer_box": res})
    return jsonify({"success": False, "error": f"Could not evaluate expression or conversion '{expr}'"}), 400

if __name__ == "__main__":
    print("[NTA-WEBSEARCH] 🚀 Starting Sovereign Search Server on port 3001...", flush=True)
    # Start Chromium daemon in background thread
    import threading
    threading.Thread(target=chromium_driver.ensure_chromium_running, daemon=True).start()
    app.run(host="0.0.0.0", port=3001, threaded=True)
