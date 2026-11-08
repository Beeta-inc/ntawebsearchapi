#!/usr/bin/env python3
"""
Heavy Stress & Comprehensive Verification Test Suite
===================================================
Tests all features across ntawebsearchapi (Port 3001) and ntamediaserver (Port 3000):
- Telemetry & Health Checks
- Sovereign Math & Unit Conversion Engine
- Reddit Discussions Engine (Filters, Subreddits, Sorting)
- GitHub Ecosystem Engine (Search, Profile, Repo Details, Trending)
- Amazon Multi-Country Autocomplete (US, UK, JP)
- YouTube Video & Channel Authority Engine (Badges, Handles, Views)
- YouTube Video Content Reader (Fast Captions, Cue Timestamps, Cache)
- OpenStreetMap Places Geocoding Engine (Coordinates, Display Names)
- Organic Web Search & AI Synthesis (/search, /api/search)
- Web Scraping Engine (/api/scrape)
- API Key Lifecycle Management (Create, List, Revoke, Delete)
- High-Concurrency Stress Test (20 parallel multi-engine requests)
"""

import sys
import time
import json
import subprocess
import urllib.request
import urllib.parse
import urllib.error
import concurrent.futures
from typing import Dict, Any, Tuple, List

BASE_3000 = "http://127.0.0.1:3000"
BASE_3001 = "http://127.0.0.1:3001"

passed_tests = 0
failed_tests = 0
test_results = []

def ensure_port_forwards():
    """Guarantees ADB port forwards are actively bound to HNJ03E0Z."""
    try:
        subprocess.run(["adb", "-s", "HNJ03E0Z", "forward", "tcp:3000", "tcp:3000"], capture_output=True, timeout=3)
        subprocess.run(["adb", "-s", "HNJ03E0Z", "forward", "tcp:3001", "tcp:3001"], capture_output=True, timeout=3)
        subprocess.run(["adb", "-s", "HNJ03E0Z", "forward", "tcp:3002", "tcp:3002"], capture_output=True, timeout=3)
    except Exception:
        pass

def make_req(url: str, method: str = "GET", data: Dict = None, headers: Dict = None, timeout: float = 25.0) -> Tuple[int, Any, float]:
    t0 = time.time()
    if headers is None:
        headers = {}
    if "User-Agent" not in headers:
        headers["User-Agent"] = "Heavy-Test-Suite/1.0"
        
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
        # Re-ensure forwards on connection error
        ensure_port_forwards()
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

ensure_port_forwards()

print("=" * 80)
print("🚀 LAUNCHING COMPREHENSIVE HEAVY TEST SUITE ON PHONE CLUSTER")
print("Target Hosts: 127.0.0.1:3000 (MediaServer) | 127.0.0.1:3001 (SearchAPI)")
print("=" * 80)

# =========================================================================
# 1. CORE TELEMETRY & HEALTH CHECKS
# =========================================================================
print("\n[SECTION 1: Core Telemetry & Cluster Health]")

st, body, el = make_req(f"{BASE_3000}/api/health")
ok = st == 200 and isinstance(body, dict) and body.get("node") == "ntamediaserver" and body.get("device", {}).get("arch") == "aarch64"
record_test("Port 3000 /api/health Telemetry", ok, el, f"Node: {body.get('node', '') if isinstance(body, dict) else ''}, Battery: {body.get('battery', {}).get('level', '') if isinstance(body, dict) else ''}%")

st, body, el = make_req(f"{BASE_3001}/status")
ok = st == 200 and isinstance(body, dict) and body.get("status") == "healthy"
record_test("Port 3001 /status Health", ok, el, f"Status: {body.get('status', '') if isinstance(body, dict) else ''}, Uptime: {body.get('uptime_sec', 0) if isinstance(body, dict) else 0}s")

st, body, el = make_req(f"{BASE_3001}/docs")
ok = st == 200 and ("Swagger" in str(body) or "API Documentation" in str(body) or "html" in str(body).lower())
record_test("Port 3001 /docs Documentation UI", ok, el, f"Docs HTML size: {len(body)} bytes")

# =========================================================================
# 2. SOVEREIGN MATH & UNIT CONVERSION ENGINE
# =========================================================================
print("\n[SECTION 2: Sovereign Math & Unit Conversion Engine]")

st, body, el = make_req(f"{BASE_3001}/api/calc?expr=125*8-45/5")
ans = (body.get("answer_box") or {}).get("answer", "") if isinstance(body, dict) else ""
ok = st == 200 and "991" in str(ans)
record_test("Math Arithmetic (125*8 - 45/5)", ok, el, f"Result: {ans}")

st, body, el = make_req(f"{BASE_3001}/api/calc?expr=sqrt(256)%2Bsin(pi/2)")
ans = (body.get("answer_box") or {}).get("answer", "") if isinstance(body, dict) else ""
ok = st == 200 and "17" in str(ans)
record_test("Scientific Math (sqrt(256) + sin(pi/2))", ok, el, f"Result: {ans}")

st, body, el = make_req(f"{BASE_3001}/api/calc?expr=50+miles+in+km")
ans = (body.get("answer_box") or {}).get("answer", "") if isinstance(body, dict) else ""
ok = st == 200 and "80.4" in str(ans)
record_test("Unit Conversion (50 miles in km)", ok, el, f"Result: {ans}")

st, body, el = make_req(f"{BASE_3001}/api/calc?expr=100+f+to+c")
ans = (body.get("answer_box") or {}).get("answer", "") if isinstance(body, dict) else ""
ok = st == 200 and "37.7" in str(ans)
record_test("Temperature Conversion (100 F to C)", ok, el, f"Result: {ans}")

st, body, el = make_req(f"{BASE_3001}/api/calc?expr=16+gb+to+mb")
ans = (body.get("answer_box") or {}).get("answer", "") if isinstance(body, dict) else ""
ok = st == 200 and ("16000" in str(ans) or "16384" in str(ans))
record_test("Data Size Conversion (16 GB in MB)", ok, el, f"Result: {ans}")

st, body, el = make_req(f"{BASE_3001}/search?q=500*24")
ans = (body.get("answer_box") or {}).get("answer", "") if isinstance(body, dict) else ""
ok = st == 200 and "12000" in str(ans)
record_test("SerpAPI Calculator Interception (/search?q=500*24)", ok, el, f"Result: {ans}")

# =========================================================================
# 3. REDDIT DISCUSSIONS ENGINE
# =========================================================================
print("\n[SECTION 3: Reddit Sovereign Discussions Engine]")

st, body, el = make_req(f"{BASE_3001}/api/reddit/search?q=python+asyncio&limit=4")
posts = (body.get("reddit_results") or body.get("organic_results") or []) if isinstance(body, dict) else []
ok = st == 200 and len(posts) > 0 and "title" in posts[0]
record_test("Reddit Global Search (q=python asyncio)", ok, el, f"Found {len(posts)} posts, Top: '{posts[0].get('title', '')[:40] if posts else ''}...'")

st, body, el = make_req(f"{BASE_3001}/api/reddit/search?q=kernel&subreddit=linux&limit=3")
posts = (body.get("reddit_results") or body.get("organic_results") or []) if isinstance(body, dict) else []
ok = st == 200 and len(posts) > 0 and any("linux" in p.get("subreddit", "").lower() or "linux" in p.get("title", "").lower() for p in posts)
record_test("Reddit Subreddit Filter (r/linux)", ok, el, f"Found {len(posts)} posts in r/linux")

st, body, el = make_req(f"{BASE_3001}/search?engine=reddit&q=gaming&sort=top&time=month&num=3")
posts = (body.get("reddit_results") or body.get("organic_results") or []) if isinstance(body, dict) else []
ok = st == 200 and len(posts) > 0
record_test("SerpAPI Reddit Engine Drop-In (engine=reddit)", ok, el, f"Returned {len(posts)} posts")

# =========================================================================
# 4. GITHUB REPOSITORIES & PROFILES ENGINE
# =========================================================================
print("\n[SECTION 4: GitHub Sovereign Ecosystem Engine]")

# Repository Search
st, body, el = make_req(f"{BASE_3001}/search?engine=github&q=fastapi&num=3")
repos = body.get("organic_results", []) if isinstance(body, dict) else []
ok = st == 200 and len(repos) > 0 and "stars" in repos[0]
record_test("GitHub Repo Search (q=fastapi)", ok, el, f"Found {len(repos)} repos, Top: {repos[0].get('repo_name', '')} ({repos[0].get('stars', '')} stars)")

# Profile Lookup
st, body, el = make_req(f"{BASE_3001}/api/github/profile?user=torvalds")
prof = body.get("profile", {}) if isinstance(body, dict) else {}
ok = st == 200 and prof.get("username") == "torvalds" and prof.get("followers", 0) > 100000
record_test("GitHub Profile Lookup (user=torvalds)", ok, el, f"Name: {prof.get('name', '')}, Followers: {prof.get('followers', 0):,}")

# Repository Details
st, body, el = make_req(f"{BASE_3001}/api/github/repo?repo=torvalds/linux")
repo_d = body.get("repository", {}) if isinstance(body, dict) else {}
ok = st == 200 and repo_d.get("full_name") == "torvalds/linux" and repo_d.get("stars", 0) > 100000
record_test("GitHub Repo Details (repo=torvalds/linux)", ok, el, f"Stars: {repo_d.get('stars', 0):,}, Forks: {repo_d.get('forks', 0):,}")

# Trending Repositories
st, body, el = make_req(f"{BASE_3001}/api/github/trending?since=daily")
trend = body.get("trending_repositories", []) if isinstance(body, dict) else []
ok = st == 200 and len(trend) > 0 and "repo" in trend[0]
record_test("GitHub Trending (since=daily)", ok, el, f"Found {len(trend)} trending repos, #1: {trend[0].get('repo', '') if trend else ''}")

# =========================================================================
# 5. AMAZON PRODUCT AUTOCOMPLETE ENGINE
# =========================================================================
print("\n[SECTION 5: Amazon Product Autocomplete Engine]")

for country in ["us", "uk", "jp"]:
    st, body, el = make_req(f"{BASE_3001}/api/amazon/autocomplete?q=mechanical+key&country={country}")
    suggs = body.get("suggestions", []) if isinstance(body, dict) else []
    top_val = (suggs[0].get("suggestion") or suggs[0].get("value") or "") if suggs else ""
    ok = st == 200 and len(suggs) > 0 and bool(top_val)
    record_test(f"Amazon Autocomplete ({country.upper()})", ok, el, f"Found {len(suggs)} suggestions, Top: '{top_val}'")

# =========================================================================
# 6. YOUTUBE VIDEO & CHANNEL AUTHORITY SEARCH
# =========================================================================
print("\n[SECTION 6: YouTube Video Search & Channel Authority Engine]")

st, body, el = make_req(f"{BASE_3001}/api/youtube/search?q=electronics+repair+school&limit=3")
vids = body.get("youtube_results", []) if isinstance(body, dict) else []
ok = st == 200 and len(vids) > 0 and vids[0].get("channel_badge") == "Verified" and bool(vids[0].get("channel_url"))
record_test("YouTube Search with Verified Badge & Channel URL", ok, el, f"Channel: {vids[0].get('channel', '') if vids else ''} ({vids[0].get('channel_badge', '') if vids else ''}), URL: {vids[0].get('channel_url', '') if vids else ''}")

st, body, el = make_req(f"{BASE_3001}/search?engine=youtube&q=spacex+starship&num=3")
vids = body.get("organic_results", []) if isinstance(body, dict) else []
ok = st == 200 and len(vids) > 0 and "video_id" in vids[0] and "duration" in vids[0]
record_test("SerpAPI YouTube Engine Drop-In (engine=youtube)", ok, el, f"Found {len(vids)} videos, Top: '{vids[0].get('title', '')[:40] if vids else ''}...' ({vids[0].get('duration', '') if vids else ''})")

# =========================================================================
# 7. YOUTUBE VIDEO CONTENT READER (read_video)
# =========================================================================
print("\n[SECTION 7: YouTube Video Content Reader (Captions & STT)]")

# Fast-Path Caption Reading (SpaceX Starship 8ySMdUIF3cY)
st, body, el = make_req(f"{BASE_3001}/api/youtube/read?v=8ySMdUIF3cY")
ok = st == 200 and isinstance(body, dict) and body.get("status") == "Success" and body.get("word_count", 0) > 1000
record_test("YouTube Video Reader (8ySMdUIF3cY)", ok, el, f"Words: {body.get('word_count', 0)}, Source: {body.get('transcript_source', '')}, Segments: {body.get('segments_count', 0)}")

# Sub-millisecond Cache Retrieval Test
st, body, el = make_req(f"{BASE_3001}/api/youtube/read?v=8ySMdUIF3cY")
ok = st == 200 and isinstance(body, dict) and body.get("cached") is True and el < 0.100
record_test("YouTube Reader Sub-Millisecond Cache Hit", ok, el, f"Cached: {body.get('cached')}, Time: {el*1000:.1f}ms")

# SerpAPI Drop-In Endpoint: /search?engine=youtube_read&v=...
st, body, el = make_req(f"{BASE_3001}/search?engine=youtube_read&v=8ySMdUIF3cY")
ok = st == 200 and isinstance(body, dict) and body.get("status") == "Success" and body.get("word_count", 0) > 1000
record_test("SerpAPI Drop-In Route (engine=youtube_read)", ok, el, f"Title: '{body.get('title', '')[:35]}...', Cached: {body.get('cached')}")

# =========================================================================
# 8. OPENSTREETMAP PLACES & GEOCODING ENGINE
# =========================================================================
print("\n[SECTION 8: OpenStreetMap Places & Geocoding Engine]")

st, body, el = make_req(f"{BASE_3001}/api/places/search?q=Empire+State+Building+New+York&limit=2")
places = (body.get("local_results") or body.get("places") or body.get("organic_results") or []) if isinstance(body, dict) else []
lat = places[0].get("latitude") or places[0].get("lat") if places else ""
lon = places[0].get("longitude") or places[0].get("lon") if places else ""
ok = st == 200 and len(places) > 0 and bool(lat) and bool(lon)
record_test("Places Search (Empire State Building)", ok, el, f"Lat: {lat}, Lon: {lon}, Name: '{places[0].get('title', '')[:40] if places else ''}'")

st, body, el = make_req(f"{BASE_3001}/search?engine=places&q=Eiffel+Tower+Paris&num=2")
places = (body.get("local_results") or body.get("organic_results") or []) if isinstance(body, dict) else []
lat = places[0].get("latitude") or places[0].get("lat") if places else ""
lon = places[0].get("longitude") or places[0].get("lon") if places else ""
ok = st == 200 and len(places) > 0 and bool(lat)
record_test("SerpAPI Places Drop-In (engine=places)", ok, el, f"Lat: {lat}, Lon: {lon}")

# =========================================================================
# 9. ORGANIC WEB SEARCH & AI SEARCH SYNTHESIS
# =========================================================================
print("\n[SECTION 9: Organic Web Search & AI Synthesis Engine]")

st, body, el = make_req(f"{BASE_3001}/search?q=CES+2026+announcements&num=4")
res = body.get("organic_results", []) if isinstance(body, dict) else []
ok = st == 200 and len(res) > 0 and "link" in res[0]
record_test("Organic Web Search (/search?q=CES 2026)", ok, el, f"Found {len(res)} results, Top: '{res[0].get('title', '')[:40] if res else ''}...'")

st, body, el = make_req(f"{BASE_3001}/api/search?q=solar+eclipse&num=3")
obs = body.get("observation", "") if isinstance(body, dict) else ""
res = body.get("results", []) if isinstance(body, dict) else []
ok = st == 200 and len(res) > 0 and len(obs) > 50
record_test("Modern AI Search Synthesis (/api/search)", ok, el, f"Synthesized observation: {len(obs)} chars, Results: {len(res)}")

# =========================================================================
# 10. DEEP WEB PAGE SCRAPER
# =========================================================================
print("\n[SECTION 10: Deep Web Page Scraper]")

st, body, el = make_req(f"{BASE_3001}/api/scrape?url=https://example.com")
text_content = (body.get("content_text") or body.get("text") or body.get("content") or "") if isinstance(body, dict) else ""
ok = st == 200 and ("example" in text_content.lower() or "example domain" in (body.get("title") or "").lower())
record_test("Web Scraper (/api/scrape?url=https://example.com)", ok, el, f"Title: '{body.get('title', '') if isinstance(body, dict) else ''}', Content: {len(text_content)} chars")

# =========================================================================
# 11. API KEY AUTHENTICATION & LIFECYCLE
# =========================================================================
print("\n[SECTION 11: API Key Lifecycle & Authentication]")

# List keys
st, body, el = make_req(f"{BASE_3001}/api/keys")
initial_keys = body.get("keys", []) if isinstance(body, dict) else []
ok = st == 200 and isinstance(initial_keys, list)
record_test("API Keys List (/api/keys)", ok, el, f"Active keys count: {len(initial_keys)}")

# Create test key
test_key_name = f"heavy_test_{int(time.time())}"
st, body, el = make_req(f"{BASE_3001}/api/keys/create", method="POST", data={"name": test_key_name})
new_key_id = (body or {}).get("key_id", "") if isinstance(body, dict) else ""
new_key_secret = (body or {}).get("api_key", "") if isinstance(body, dict) else ""
ok = st == 201 and bool(new_key_id) and new_key_secret.startswith("nta_live_")
record_test("API Key Creation (/api/keys/create)", ok, el, f"Key ID: {new_key_id}, Secret prefix: {new_key_secret[:14]}...")

# Verify search access with new key
if new_key_secret:
    st, body, el = make_req(f"{BASE_3001}/search?q=test&api_key={new_key_secret}")
    ok = st == 200 and isinstance(body, dict)
    record_test("API Key Authorization Check", ok, el, f"Status: {st}")

# Revoke & Delete test key
if new_key_id:
    st, body, el = make_req(f"{BASE_3001}/api/keys/revoke", method="POST", data={"key_id": new_key_id})
    ok_revoke = st == 200
    st, body, el = make_req(f"{BASE_3001}/api/keys/delete", method="POST", data={"key_id": new_key_id})
    ok_del = st == 200
    record_test("API Key Cleanup (Revoke & Delete)", ok_revoke and ok_del, el, f"Revoke: {ok_revoke}, Delete: {ok_del}")

# =========================================================================
# 12. HIGH-CONCURRENCY MULTI-THREADED STRESS TEST (20 PARALLEL REQUESTS)
# =========================================================================
print("\n[SECTION 12: High-Concurrency Multi-Engine Stress Test (20 Parallel Threads)]")

ensure_port_forwards()

test_endpoints = [
    f"{BASE_3000}/api/health",
    f"{BASE_3001}/status",
    f"{BASE_3001}/api/calc?expr=15*15",
    f"{BASE_3001}/api/calc?expr=100+miles+to+km",
    f"{BASE_3001}/api/calc?expr=50+c+to+f",
    f"{BASE_3001}/api/amazon/autocomplete?q=macbook&country=us",
    f"{BASE_3001}/api/amazon/autocomplete?q=sony&country=jp",
    f"{BASE_3001}/api/reddit/search?q=technology&limit=3",
    f"{BASE_3001}/api/github/trending?since=daily",
    f"{BASE_3001}/api/github/profile?user=torvalds",
    f"{BASE_3001}/api/places/search?q=London+Eye&limit=2",
    f"{BASE_3001}/api/youtube/read?v=8ySMdUIF3cY",
    f"{BASE_3001}/api/youtube/search?q=spacex&limit=2",
    f"{BASE_3001}/search?engine=places&q=Tokyo+Tower&num=2",
    f"{BASE_3001}/search?q=linux+foundation",
    f"{BASE_3001}/search?engine=github&q=kubernetes&num=2",
    f"{BASE_3001}/search?engine=reddit&q=science&num=2",
    f"{BASE_3001}/search?engine=youtube_read&v=8ySMdUIF3cY",
    f"{BASE_3001}/api/scrape?url=https://example.com",
    f"{BASE_3000}/telemetry"
]

concurrent_start = time.time()
with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
    futures = {executor.submit(make_req, ep, "GET", None, None, 35.0): ep for ep in test_endpoints}
    concurrent_results = []
    for f in concurrent.futures.as_completed(futures):
        ep = futures[f]
        try:
            status, res_body, dur = f.result()
            concurrent_results.append((ep, status, dur))
        except Exception as exc:
            concurrent_results.append((ep, 0, 0.0))

concurrent_total_time = time.time() - concurrent_start
successful_concurrent = sum(1 for _, st, _ in concurrent_results if st in [200, 201])

ok = successful_concurrent >= 18 # allow at most 2 edge transients under heavy flood
record_test(
    f"20 Concurrent Multi-Engine Parallel Requests ({successful_concurrent}/{len(test_endpoints)} Succeeded)",
    ok,
    concurrent_total_time,
    f"Total Concurrency Time: {concurrent_total_time:.2f}s, Avg per thread: {concurrent_total_time/len(test_endpoints):.3f}s"
)

# Print Detailed Concurrent Breakdown
for ep, st, dur in sorted(concurrent_results, key=lambda x: x[2]):
    parsed = urllib.parse.urlparse(ep)
    short_ep = parsed.path + ("?" + parsed.query if parsed.query else "")
    if len(short_ep) > 55:
        short_ep = short_ep[:52] + "..."
    status_icon = "🟢" if st in [200, 201] else "🔴"
    print(f"   {status_icon} [{st}] in {dur:.3f}s -> {parsed.netloc}{short_ep}")

# =========================================================================
# FINAL SCORE & SUMMARY REPORT
# =========================================================================
print("\n" + "=" * 80)
print(f"📊 HEAVY TEST SUITE COMPLETED: {passed_tests} PASSED | {failed_tests} FAILED")
print(f"Total Tests Executed: {passed_tests + failed_tests}")
print(f"Success Rate: {(passed_tests / (passed_tests + failed_tests)) * 100:.1f}%")
print("=" * 80)

if failed_tests > 0:
    sys.exit(1)
sys.exit(0)
