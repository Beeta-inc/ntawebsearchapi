#!/usr/bin/env python3
"""
Public Edge Comprehensive Verification & Heavy Stress Test Suite
================================================================
Target Domains (Pure Internet, ZERO ADB / Localhost):
- https://ntamediaserver.pages.dev (Port 3000 MediaServer & Telemetry Hub)
- https://ntawebsearch.pages.dev   (Port 3001 Search API Hub)

Verifies all sovereign subsystems over the live public Cloudflare edge tunnels.
"""

import sys
import time
import json
import urllib.request
import urllib.parse
import urllib.error
import concurrent.futures
from typing import Dict, Any, Tuple, List

BASE_MEDIA = "https://ntamediaserver.pages.dev"
BASE_SEARCH = "https://ntawebsearch.pages.dev"

passed_tests = 0
failed_tests = 0
test_results = []

def make_req(url: str, method: str = "GET", data: Dict = None, headers: Dict = None, timeout: float = 35.0) -> Tuple[int, Any, float]:
    t0 = time.time()
    if headers is None:
        headers = {}
    if "User-Agent" not in headers:
        headers["User-Agent"] = "NeTuArk-Public-Edge-Tester/2.0"
        
    req_body = None
    if data is not None:
        req_body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
        
    req = urllib.request.Request(url, data=req_body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed = time.time() - t0
            raw = resp.read().decode("utf-8", "ignore")
            try:
                body = json.loads(raw)
            except Exception:
                body = raw
            return resp.status, body, elapsed
    except urllib.error.HTTPError as he:
        elapsed = time.time() - t0
        err_raw = he.read().decode("utf-8", "ignore")
        try:
            body = json.loads(err_raw)
        except Exception:
            body = err_raw
        return he.code, body, elapsed
    except Exception as e:
        elapsed = time.time() - t0
        return 0, str(e), elapsed

def record_test(name: str, passed: bool, elapsed: float, details: str = ""):
    global passed_tests, failed_tests
    if passed:
        passed_tests += 1
        status_sym = "✅ PASS"
    else:
        failed_tests += 1
        status_sym = "❌ FAIL"
    msg = f"{status_sym} | {elapsed:.3f}s | {name}"
    if details:
        msg += f" -> {details}"
    print(msg, flush=True)
    test_results.append({
        "name": name,
        "passed": passed,
        "elapsed": elapsed,
        "details": details
    })

print("=" * 80)
print("🚀 LAUNCHING PUBLIC EDGE HEAVY TEST SUITE (PURE INTERNET / ZERO ADB)")
print(f"Target Media Host:  {BASE_MEDIA}")
print(f"Target Search Host: {BASE_SEARCH}")
print("=" * 80)

# Create active session key for authorized search requests
print("\n[PRE-TEST: Provisioning Session API Key for Authenticated Endpoints]")
st, key_data, el = make_req(f"{BASE_SEARCH}/createapi", method="POST", data={"owner": "edge_heavy_tester"})
SESSION_KEY = (key_data.get("api_key") if isinstance(key_data, dict) else "") or ""
SESSION_KEY_ID = (key_data.get("key_id") if isinstance(key_data, dict) else "") or ""
print(f"[*] Session Key ID: {SESSION_KEY_ID}, Prefix: {SESSION_KEY[:14]}... (Provisioned in {el:.2f}s)")

# Helper to append api_key to search endpoints
def auth_url(url: str) -> str:
    if not SESSION_KEY:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}api_key={SESSION_KEY}"

# =========================================================================
# 1. CORE TELEMETRY & HEALTH CHECKS
# =========================================================================
print("\n[SECTION 1: Core Telemetry & Cluster Health]")

st, body, el = make_req(f"{BASE_MEDIA}/api/health")
ok = st == 200 and isinstance(body, dict) and body.get("node") == "ntamediaserver" and body.get("device", {}).get("arch") == "aarch64"
cpu_usage = (body.get("cpu") or {}).get("usage_percent", 0.0) if isinstance(body, dict) else 0.0
cpu_temp = (body.get("cpu") or {}).get("temperature_c", 0.0) if isinstance(body, dict) else 0.0
record_test(
    "MediaServer Public /api/health Telemetry",
    ok and cpu_usage > 0.0,
    el,
    f"Node: {body.get('node', '') if isinstance(body, dict) else ''}, CPU: {cpu_usage}% ({cpu_temp}°C), Battery: {body.get('battery', {}).get('level', '') if isinstance(body, dict) else ''}%"
)

st, body, el = make_req(f"{BASE_SEARCH}/status")
ok = st == 200 and isinstance(body, dict) and body.get("status") == "healthy"
record_test(
    "SearchAPI Public /status Health",
    ok,
    el,
    f"Status: {body.get('status', '') if isinstance(body, dict) else ''}, Uptime: {body.get('uptime_sec', 0) if isinstance(body, dict) else 0}s, Chromium: {body.get('chromium_active') if isinstance(body, dict) else False}"
)

st, body, el = make_req(f"{BASE_SEARCH}/docs")
ok = st == 200 and ("API Documentation" in str(body) or "html" in str(body).lower())
record_test("SearchAPI Public /docs UI", ok, el, f"HTML size: {len(body)} bytes")

# =========================================================================
# 2. SOVEREIGN MATH & UNIT CONVERSION ENGINE
# =========================================================================
print("\n[SECTION 2: Sovereign Math & Unit Conversion Engine]")

st, body, el = make_req(auth_url(f"{BASE_SEARCH}/api/calc?expr=125*8-45/5"))
ans = (body.get("answer_box") or {}).get("answer", "") if isinstance(body, dict) else ""
ok = st == 200 and "991" in str(ans)
record_test("Math Arithmetic (125*8 - 45/5)", ok, el, f"Result: {ans}")

st, body, el = make_req(auth_url(f"{BASE_SEARCH}/api/calc?expr=sqrt(256)%2Bsin(pi/2)"))
ans = (body.get("answer_box") or {}).get("answer", "") if isinstance(body, dict) else ""
ok = st == 200 and "17" in str(ans)
record_test("Scientific Math (sqrt(256) + sin(pi/2))", ok, el, f"Result: {ans}")

st, body, el = make_req(auth_url(f"{BASE_SEARCH}/api/calc?expr=50+miles+in+km"))
ans = (body.get("answer_box") or {}).get("answer", "") if isinstance(body, dict) else ""
ok = st == 200 and "80.4" in str(ans)
record_test("Unit Conversion (50 miles in km)", ok, el, f"Result: {ans}")

st, body, el = make_req(auth_url(f"{BASE_SEARCH}/api/calc?expr=100+f+to+c"))
ans = (body.get("answer_box") or {}).get("answer", "") if isinstance(body, dict) else ""
ok = st == 200 and "37.7" in str(ans)
record_test("Temperature Conversion (100 F to C)", ok, el, f"Result: {ans}")

st, body, el = make_req(auth_url(f"{BASE_SEARCH}/api/calc?expr=16+gb+to+mb"))
ans = (body.get("answer_box") or {}).get("answer", "") if isinstance(body, dict) else ""
ok = st == 200 and ("16000" in str(ans) or "16384" in str(ans))
record_test("Data Size Conversion (16 GB in MB)", ok, el, f"Result: {ans}")

st, body, el = make_req(auth_url(f"{BASE_SEARCH}/search?q=500*24"))
ans = (body.get("answer_box") or {}).get("answer", "") if isinstance(body, dict) else ""
ok = st == 200 and "12000" in str(ans)
record_test("SerpAPI Calculator Interception (/search?q=500*24)", ok, el, f"Result: {ans}")

# =========================================================================
# 3. REDDIT DISCUSSIONS ENGINE
# =========================================================================
print("\n[SECTION 3: Reddit Sovereign Discussions Engine]")

st, body, el = make_req(auth_url(f"{BASE_SEARCH}/api/reddit/search?q=python+asyncio&limit=4"))
posts = (body.get("reddit_results") or body.get("organic_results") or []) if isinstance(body, dict) else []
ok = st == 200 and len(posts) > 0 and "title" in posts[0]
record_test("Reddit Global Search (q=python asyncio)", ok, el, f"Found {len(posts)} posts, Top: '{posts[0].get('title', '')[:40] if posts else ''}...'")

st, body, el = make_req(auth_url(f"{BASE_SEARCH}/api/reddit/search?q=kernel&subreddit=linux&limit=3"))
posts = (body.get("reddit_results") or body.get("organic_results") or []) if isinstance(body, dict) else []
ok = st == 200 and len(posts) > 0
record_test("Reddit Subreddit Filter (r/linux)", ok, el, f"Found {len(posts)} posts in r/linux")

st, body, el = make_req(auth_url(f"{BASE_SEARCH}/search?engine=reddit&q=gaming&sort=top&time=month&num=3"))
posts = (body.get("reddit_results") or body.get("organic_results") or []) if isinstance(body, dict) else []
ok = st == 200 and len(posts) > 0
record_test("SerpAPI Reddit Engine Drop-In (engine=reddit)", ok, el, f"Returned {len(posts)} posts")

# =========================================================================
# 4. GITHUB REPOSITORIES & PROFILES ENGINE
# =========================================================================
print("\n[SECTION 4: GitHub Sovereign Ecosystem Engine]")

# Repository Search
st, body, el = make_req(auth_url(f"{BASE_SEARCH}/search?engine=github&q=fastapi&num=3"))
repos = body.get("organic_results", []) if isinstance(body, dict) else []
ok = st == 200 and len(repos) > 0 and "stars" in repos[0]
record_test("GitHub Repo Search (q=fastapi)", ok, el, f"Found {len(repos)} repos, Top: {repos[0].get('repo_name', '')} ({repos[0].get('stars', '')} stars)")

# Profile Lookup
st, body, el = make_req(auth_url(f"{BASE_SEARCH}/api/github/profile?user=torvalds"))
prof = body.get("profile", {}) if isinstance(body, dict) else {}
ok = st == 200 and prof.get("username") == "torvalds" and prof.get("followers", 0) > 100000
record_test("GitHub Profile Lookup (user=torvalds)", ok, el, f"Name: {prof.get('name', '')}, Followers: {prof.get('followers', 0):,}")

# Repository Details
st, body, el = make_req(auth_url(f"{BASE_SEARCH}/api/github/repo?repo=torvalds/linux"))
repo_d = body.get("repository", {}) if isinstance(body, dict) else {}
ok = st == 200 and repo_d.get("full_name") == "torvalds/linux" and repo_d.get("stars", 0) > 100000
record_test("GitHub Repo Details (repo=torvalds/linux)", ok, el, f"Stars: {repo_d.get('stars', 0):,}, Forks: {repo_d.get('forks', 0):,}")

# Trending Repositories
st, body, el = make_req(auth_url(f"{BASE_SEARCH}/api/github/trending?since=daily"))
trend = body.get("trending_repositories", []) if isinstance(body, dict) else []
ok = st == 200 and len(trend) > 0 and "repo" in trend[0]
record_test("GitHub Trending (since=daily)", ok, el, f"Found {len(trend)} trending repos, #1: {trend[0].get('repo', '') if trend else ''}")

# =========================================================================
# 5. AMAZON PRODUCT AUTOCOMPLETE ENGINE
# =========================================================================
print("\n[SECTION 5: Amazon Product Autocomplete Engine]")

for country in ["us", "uk", "jp"]:
    st, body, el = make_req(auth_url(f"{BASE_SEARCH}/api/amazon/autocomplete?q=mechanical+key&country={country}"))
    suggs = body.get("suggestions", []) if isinstance(body, dict) else []
    top_val = (suggs[0].get("suggestion") or suggs[0].get("value") or "") if suggs else ""
    ok = st == 200 and len(suggs) > 0 and bool(top_val)
    record_test(f"Amazon Autocomplete ({country.upper()})", ok, el, f"Found {len(suggs)} suggestions, Top: '{top_val}'")

# =========================================================================
# 6. YOUTUBE VIDEO & CHANNEL AUTHORITY SEARCH
# =========================================================================
print("\n[SECTION 6: YouTube Video Search & Channel Authority Engine]")

st, body, el = make_req(auth_url(f"{BASE_SEARCH}/api/youtube/search?q=electronics+repair+school&limit=3"))
vids = body.get("youtube_results", []) if isinstance(body, dict) else []
ok = st == 200 and len(vids) > 0 and vids[0].get("channel_badge") == "Verified" and bool(vids[0].get("channel_url"))
record_test("YouTube Search with Verified Badge & Channel URL", ok, el, f"Channel: {vids[0].get('channel', '') if vids else ''} ({vids[0].get('channel_badge', '') if vids else ''}), URL: {vids[0].get('channel_url', '') if vids else ''}")

st, body, el = make_req(auth_url(f"{BASE_SEARCH}/search?engine=youtube&q=spacex+starship&num=3"))
vids = body.get("organic_results", []) if isinstance(body, dict) else []
ok = st == 200 and len(vids) > 0 and "video_id" in vids[0] and "duration" in vids[0]
record_test("SerpAPI YouTube Engine Drop-In (engine=youtube)", ok, el, f"Found {len(vids)} videos, Top: '{vids[0].get('title', '')[:40] if vids else ''}...' ({vids[0].get('duration', '') if vids else ''})")

# =========================================================================
# 7. YOUTUBE VIDEO CONTENT READER (read_video)
# =========================================================================
print("\n[SECTION 7: YouTube Video Content Reader (Captions & STT)]")

# Fast-Path Caption Reading (SpaceX Starship 8ySMdUIF3cY)
st, body, el = make_req(auth_url(f"{BASE_SEARCH}/api/youtube/read?v=8ySMdUIF3cY"))
ok = st == 200 and isinstance(body, dict) and body.get("status") == "Success" and body.get("word_count", 0) > 1000
record_test("YouTube Video Reader (8ySMdUIF3cY)", ok, el, f"Words: {body.get('word_count', 0)}, Source: {body.get('transcript_source', '')}, Segments: {body.get('segments_count', 0)}")

# Sub-millisecond Cache Hit Test
st, body, el = make_req(auth_url(f"{BASE_SEARCH}/api/youtube/read?v=8ySMdUIF3cY"))
ok = st == 200 and isinstance(body, dict) and body.get("cached") is True and el < 1.000
record_test("YouTube Reader Cache Hit Over Internet Edge", ok, el, f"Cached: {body.get('cached')}, Edge Round-trip: {el*1000:.1f}ms")

# SerpAPI Drop-In Endpoint: /search?engine=youtube_read&v=...
st, body, el = make_req(auth_url(f"{BASE_SEARCH}/search?engine=youtube_read&v=8ySMdUIF3cY"))
ok = st == 200 and isinstance(body, dict) and body.get("status") == "Success" and body.get("word_count", 0) > 1000
record_test("SerpAPI Drop-In Route (engine=youtube_read)", ok, el, f"Title: '{body.get('title', '')[:35]}...', Cached: {body.get('cached')}")

# =========================================================================
# 8. OPENSTREETMAP PLACES & GEOCODING ENGINE
# =========================================================================
print("\n[SECTION 8: OpenStreetMap Places & Geocoding Engine]")

st, body, el = make_req(auth_url(f"{BASE_SEARCH}/api/places/search?q=Empire+State+Building+New+York&limit=2"))
places = (body.get("local_results") or body.get("places") or body.get("organic_results") or []) if isinstance(body, dict) else []
lat = places[0].get("latitude") or places[0].get("lat") if places else ""
lon = places[0].get("longitude") or places[0].get("lon") if places else ""
ok = st == 200 and len(places) > 0 and bool(lat) and bool(lon)
record_test("Places Search (Empire State Building)", ok, el, f"Lat: {lat}, Lon: {lon}, Name: '{places[0].get('title', '')[:40] if places else ''}'")

st, body, el = make_req(auth_url(f"{BASE_SEARCH}/search?engine=places&q=Eiffel+Tower+Paris&num=2"))
places = (body.get("local_results") or body.get("organic_results") or []) if isinstance(body, dict) else []
lat = places[0].get("latitude") or places[0].get("lat") if places else ""
lon = places[0].get("longitude") or places[0].get("lon") if places else ""
ok = st == 200 and len(places) > 0 and bool(lat)
record_test("SerpAPI Places Drop-In (engine=places)", ok, el, f"Lat: {lat}, Lon: {lon}")

# =========================================================================
# 9. ORGANIC WEB SEARCH & AI SEARCH SYNTHESIS
# =========================================================================
print("\n[SECTION 9: Organic Web Search & AI Synthesis Engine]")

st, body, el = make_req(auth_url(f"{BASE_SEARCH}/search?q=CES+2026+announcements&num=4"))
res = body.get("organic_results", []) if isinstance(body, dict) else []
ok = st == 200 and len(res) > 0 and "link" in res[0]
record_test("Organic Web Search (/search?q=CES 2026)", ok, el, f"Found {len(res)} results, Top: '{res[0].get('title', '')[:40] if res else ''}...'")

st, body, el = make_req(auth_url(f"{BASE_SEARCH}/api/search?q=solar+eclipse&num=3"))
obs = body.get("observation", "") if isinstance(body, dict) else ""
res = body.get("results", []) if isinstance(body, dict) else []
ok = st == 200 and len(res) > 0 and len(obs) > 50
record_test("Modern AI Search Synthesis (/api/search)", ok, el, f"Synthesized observation: {len(obs)} chars, Results: {len(res)}")

# =========================================================================
# 10. DEEP WEB PAGE SCRAPER
# =========================================================================
print("\n[SECTION 10: Deep Web Page Scraper]")

st, body, el = make_req(auth_url(f"{BASE_SEARCH}/api/scrape?url=https://example.com"))
text_content = (body.get("content_text") or body.get("text") or body.get("content") or "") if isinstance(body, dict) else ""
ok = st == 200 and ("example" in text_content.lower() or "example domain" in (body.get("title") or "").lower())
record_test("Web Scraper (/api/scrape?url=https://example.com)", ok, el, f"Title: '{body.get('title', '') if isinstance(body, dict) else ''}', Content: {len(text_content)} chars")

# =========================================================================
# 11. API KEY AUTHENTICATION & LIFECYCLE
# =========================================================================
print("\n[SECTION 11: API Key Lifecycle & Authentication]")

# List keys
st, body, el = make_req(f"{BASE_SEARCH}/api/keys")
initial_keys = body.get("keys", []) if isinstance(body, dict) else []
ok = st == 200 and isinstance(initial_keys, list)
record_test("API Keys List (/api/keys)", ok, el, f"Active keys count: {len(initial_keys)}")

# Create test key
test_key_name = f"public_test_{int(time.time())}"
st, body, el = make_req(f"{BASE_SEARCH}/api/keys/create", method="POST", data={"name": test_key_name})
new_key_id = (body or {}).get("key_id", "") if isinstance(body, dict) else ""
new_key_secret = (body or {}).get("api_key", "") if isinstance(body, dict) else ""
ok = st == 201 and bool(new_key_id) and new_key_secret.startswith("nta_live_")
record_test("API Key Creation (/api/keys/create)", ok, el, f"Key ID: {new_key_id}, Secret prefix: {new_key_secret[:14]}...")

# Verify search access with new key
if new_key_secret:
    st, body, el = make_req(f"{BASE_SEARCH}/search?q=test&api_key={new_key_secret}")
    ok = st == 200 and isinstance(body, dict)
    record_test("API Key Authorization Check", ok, el, f"Status: {st}")

# Revoke & Delete test key
if new_key_id:
    st, body, el = make_req(f"{BASE_SEARCH}/api/keys/revoke", method="POST", data={"key_id": new_key_id})
    ok_revoke = st == 200
    st, body, el = make_req(f"{BASE_SEARCH}/api/keys/delete", method="POST", data={"key_id": new_key_id})
    ok_del = st == 200
    record_test("API Key Cleanup (Revoke & Delete)", ok_revoke and ok_del, el, f"Revoke: {ok_revoke}, Delete: {ok_del}")

# =========================================================================
# 12. HIGH-CONCURRENCY MULTI-THREADED STRESS TEST (20 PARALLEL REQUESTS)
# =========================================================================
print("\n[SECTION 12: High-Concurrency Multi-Engine Stress Test (20 Parallel Threads)]")

test_endpoints = [
    f"{BASE_MEDIA}/api/health",
    f"{BASE_SEARCH}/status",
    auth_url(f"{BASE_SEARCH}/api/calc?expr=15*15"),
    auth_url(f"{BASE_SEARCH}/api/calc?expr=100+miles+to+km"),
    auth_url(f"{BASE_SEARCH}/api/calc?expr=50+c+to+f"),
    auth_url(f"{BASE_SEARCH}/api/amazon/autocomplete?q=macbook&country=us"),
    auth_url(f"{BASE_SEARCH}/api/amazon/autocomplete?q=sony&country=jp"),
    auth_url(f"{BASE_SEARCH}/api/reddit/search?q=technology&limit=3"),
    auth_url(f"{BASE_SEARCH}/api/github/trending?since=daily"),
    auth_url(f"{BASE_SEARCH}/api/github/profile?user=torvalds"),
    auth_url(f"{BASE_SEARCH}/api/github/repo?repo=torvalds/linux"),
    auth_url(f"{BASE_SEARCH}/api/places/search?q=Tokyo+Tower"),
    auth_url(f"{BASE_SEARCH}/api/places/search?q=Big+Ben+London"),
    auth_url(f"{BASE_SEARCH}/api/youtube/search?q=veritasium&limit=2"),
    auth_url(f"{BASE_SEARCH}/api/youtube/read?v=8ySMdUIF3cY"),
    auth_url(f"{BASE_SEARCH}/search?engine=youtube_read&v=8ySMdUIF3cY"),
    auth_url(f"{BASE_SEARCH}/search?q=2048*16"),
    auth_url(f"{BASE_SEARCH}/api/amazon/autocomplete?q=kindle&country=uk"),
    f"{BASE_MEDIA}/api/health",
    f"{BASE_SEARCH}/status"
]

concurrency_start = time.time()
concurrent_success = 0
concurrent_failures = 0

def worker(ep_url: str):
    st, resp_data, req_time = make_req(ep_url, timeout=35.0)
    return ep_url, st, req_time

with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
    futures = [executor.submit(worker, url) for url in test_endpoints]
    for future in concurrent.futures.as_completed(futures):
        ep_url, st, req_time = future.result()
        if st in [200, 201]:
            concurrent_success += 1
        else:
            concurrent_failures += 1
            print(f"   [!] Concurrency failure: {ep_url} returned status {st}", flush=True)

total_concurrency_time = time.time() - concurrency_start
ok_concurrency = concurrent_failures == 0 and concurrent_success == len(test_endpoints)
record_test(
    f"20-Thread Multi-Engine Edge Concurrency Stress Test",
    ok_concurrency,
    total_concurrency_time,
    f"Dispatched {len(test_endpoints)} parallel requests: {concurrent_success} passed, {concurrent_failures} failed (Avg: {total_concurrency_time/len(test_endpoints):.3f}s/req)"
)
# Clean up test session key
if SESSION_KEY_ID:
    make_req(f"{BASE_SEARCH}/api/keys/revoke", method="POST", data={"key_id": SESSION_KEY_ID})
    make_req(f"{BASE_SEARCH}/api/keys/delete", method="POST", data={"key_id": SESSION_KEY_ID})

# =========================================================================
# FINAL VERIFICATION SCOREBOARD
# =========================================================================
print("\n" + "=" * 80)
print("🏁 PUBLIC EDGE CLUSTER VERIFICATION SUMMARY (ZERO ADB / FULL PROD)")
print("=" * 80)
print(f"Total Tests Executed: {passed_tests + failed_tests}")
print(f"Passed:              {passed_tests}")
print(f"Failed:              {failed_tests}")
success_pct = (passed_tests / (passed_tests + failed_tests)) * 100 if (passed_tests + failed_tests) > 0 else 0
print(f"Success Rate:        {success_pct:.1f}%")
print("=" * 80)

if failed_tests > 0:
    print(f"\n❌ FAILED TESTS SUMMARY ({failed_tests}):")
    for r in test_results:
        if not r["passed"]:
            print(f"  - {r['name']}: {r['details']} ({r['elapsed']:.2f}s)")
    sys.exit(1)
else:
    print("\n🎉 ALL 34 SOVEREIGN CLUSTER SUBSYSTEM TESTS PASSED WITH 100% SUCCESS OVER PUBLIC EDGE!")
    sys.exit(0)
