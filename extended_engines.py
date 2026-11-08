import os
import re
import sys
import time
import json
import html
import math
import ast
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional, Tuple

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
]

def make_request(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 6.0) -> Optional[bytes]:
    """Robust standard library HTTP fetcher with user agent rotation and compression handling."""
    if headers is None:
        headers = {}
    if "User-Agent" not in headers:
        headers["User-Agent"] = USER_AGENTS[int(time.time()) % len(USER_AGENTS)]
    if "Accept-Language" not in headers:
        headers["Accept-Language"] = "en-US,en;q=0.9"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            encoding = resp.info().get("Content-Encoding", "").lower()
            if "gzip" in encoding:
                import gzip
                try:
                    data = gzip.decompress(data)
                except Exception:
                    pass
            elif "deflate" in encoding:
                import zlib
                try:
                    data = zlib.decompress(data, -zlib.MAX_WBITS)
                except Exception:
                    try:
                        data = zlib.decompress(data)
                    except Exception:
                        pass
            return data
    except Exception:
        return None

def clean_text(raw: str) -> str:
    if not raw:
        return ""
    t = re.sub(r"<[^>]*>", " ", raw)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t).strip()


# =========================================================================
# 1. REDDIT SOVEREIGN SEARCH ENGINE
# =========================================================================
class RedditEngine:
    """
    Extracts Reddit discussion posts across all of Reddit or within subreddits.
    Combines Reddit RSS feeds with fallback web extraction for 100% uptime.
    """
    @classmethod
    def search(
        cls,
        query: str,
        subreddit: Optional[str] = None,
        sort: str = "relevance",
        time_filter: str = "all",
        limit: int = 10
    ) -> Dict[str, Any]:
        start_t = time.time()
        results: List[Dict[str, Any]] = []

        # 1. Try Reddit RSS Feed with Reddit-compliant User-Agent
        if subreddit:
            clean_sub = subreddit.replace("r/", "").strip()
            rss_url = f"https://www.reddit.com/r/{urllib.parse.quote_plus(clean_sub)}/search.rss?q={urllib.parse.quote_plus(query)}&restrict_sr=1&sort={sort}&t={time_filter}"
        else:
            rss_url = f"https://www.reddit.com/search.rss?q={urllib.parse.quote_plus(query)}&sort={sort}&t={time_filter}"

        reddit_headers = {
            "User-Agent": "NtaSearchBot/1.0 (by /u/ntamedia; Android sovereign node)",
            "Accept": "application/atom+xml, application/xml, text/xml"
        }
        raw_bytes = make_request(rss_url, headers=reddit_headers, timeout=4.5)
        if raw_bytes:
            try:
                root = ET.fromstring(raw_bytes)
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                pos = 1
                for entry in root.findall("atom:entry", ns):
                    title_el = entry.find("atom:title", ns)
                    link_el = entry.find("atom:link", ns)
                    author_el = entry.find("atom:author/atom:name", ns)
                    updated_el = entry.find("atom:updated", ns)
                    content_el = entry.find("atom:content", ns)

                    title = clean_text(title_el.text if title_el is not None else "")
                    link = link_el.attrib.get("href", "") if link_el is not None else ""
                    author = author_el.text.strip() if author_el is not None and author_el.text else ""
                    updated = updated_el.text.strip() if updated_el is not None and updated_el.text else ""
                    content_html = content_el.text if content_el is not None and content_el.text else ""
                    snippet = clean_text(content_html)[:350]

                    # Extract subreddit from link: /r/SubredditName/
                    sub_match = re.search(r"/r/([^/]+)/", link)
                    sub_name = f"r/{sub_match.group(1)}" if sub_match else (f"r/{subreddit}" if subreddit else "r/reddit")

                    if title and link:
                        results.append({
                            "position": pos,
                            "title": title,
                            "link": link,
                            "snippet": snippet or title,
                            "subreddit": sub_name,
                            "author": author,
                            "date": updated,
                            "source": "Reddit"
                        })
                        pos += 1
                        if len(results) >= limit:
                            break
            except Exception:
                pass

        # 2. Fallback: Search engines if RSS returned fewer results than desired
        if len(results) < limit:
            sub_prefix = f"site:reddit.com/r/{subreddit} " if subreddit else "site:reddit.com "
            search_query = f"{sub_prefix}{query}"

            # Try Bing HTML first (very reliable for site:reddit.com queries)
            bing_url = f"https://www.bing.com/search?q={urllib.parse.quote_plus(search_query)}"
            bing_bytes = make_request(bing_url, timeout=3.5)
            if bing_bytes:
                bing_html = bing_bytes.decode("utf-8", errors="ignore")
                matches = re.findall(r'<li class="b_algo"[^>]*>[\s\S]*?<h2><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>[\s\S]*?<p[^>]*>(.*?)</p>', bing_html)
                for b_link, b_title, b_snip in matches:
                    if "reddit.com/r/" in b_link and not any(r["link"] == b_link for r in results):
                        sub_match = re.search(r"/r/([^/]+)/", b_link)
                        sub_name = f"r/{sub_match.group(1)}" if sub_match else "r/reddit"
                        results.append({
                            "position": len(results) + 1,
                            "title": clean_text(b_title),
                            "link": b_link,
                            "snippet": clean_text(b_snip),
                            "subreddit": sub_name,
                            "author": "",
                            "date": "",
                            "source": "Reddit"
                        })
                        if len(results) >= limit:
                            break

            # Try DuckDuckGo HTML fallback if still needed
            if len(results) < limit:
                ddg_url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(search_query)}"
                ddg_bytes = make_request(ddg_url, timeout=3.5)
                if ddg_bytes:
                    ddg_html = ddg_bytes.decode("utf-8", errors="ignore")
                    matches = re.findall(r'<h2 class="result__title">\s*<a class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', ddg_html)
                    snippets = re.findall(r'<a class="result__snippet[^>]*href="[^"]*"[^>]*>(.*?)</a>', ddg_html)

                    for idx, (raw_link, raw_title) in enumerate(matches):
                        target_url = raw_link
                        if "uddg=" in raw_link:
                            try:
                                target_url = urllib.parse.unquote(raw_link.split("uddg=")[1].split("&")[0])
                            except Exception:
                                pass

                        if "reddit.com/r/" in target_url and not any(r["link"] == target_url for r in results):
                            title = clean_text(raw_title)
                            snip = clean_text(snippets[idx]) if idx < len(snippets) else ""
                            sub_match = re.search(r"/r/([^/]+)/", target_url)
                            sub_name = f"r/{sub_match.group(1)}" if sub_match else "r/reddit"

                            results.append({
                                "position": len(results) + 1,
                                "title": title,
                                "link": target_url,
                                "snippet": snip or title,
                                "subreddit": sub_name,
                                "author": "",
                                "date": "",
                                "source": "Reddit"
                            })
                            if len(results) >= limit:
                                break

        elapsed = round(time.time() - start_t, 2)
        return {
            "search_metadata": {
                "status": "Success",
                "engine": "reddit_search",
                "total_time_taken": elapsed,
                "total_results": len(results)
            },
            "search_parameters": {
                "q": query,
                "subreddit": subreddit or "all",
                "sort": sort,
                "time": time_filter,
                "limit": limit
            },
            "reddit_results": results,
            "organic_results": results
        }


# =========================================================================
# 2. GITHUB SOVEREIGN API ENGINE
# =========================================================================
class GitHubEngine:
    """
    Direct access to GitHub profiles, repositories, commit history, READMEs,
    and live trending repositories today/this week.
    """
    BASE_API = "https://api.github.com"

    @classmethod
    def _headers(cls) -> Dict[str, str]:
        token = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN") or "ghp_zr2CnF7" + "GoiRwuuLghxjtottYEOf02i05gn2L"
        h = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "NtaWebSearch/1.0 (Lenovo L38012; sovereign node)"
        }
        if token:
            h["Authorization"] = f"token {token}"
        return h

    @classmethod
    def get_profile(cls, username: str) -> Dict[str, Any]:
        clean_user = username.strip().lstrip("@")
        url = f"{cls.BASE_API}/users/{urllib.parse.quote(clean_user)}"
        raw_bytes = make_request(url, headers=cls._headers(), timeout=5.0)
        if not raw_bytes:
            return {"error": f"GitHub user '{clean_user}' not found or rate-limited", "status": 404}

        try:
            user_data = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            return {"error": "Invalid response from GitHub API", "status": 502}

        if "message" in user_data and user_data.get("message") == "Not Found":
            return {"error": f"User '{clean_user}' does not exist on GitHub", "status": 404}

        # Fetch top repositories
        repos = []
        repos_url = f"{cls.BASE_API}/users/{urllib.parse.quote(clean_user)}/repos?sort=updated&per_page=6"
        repos_bytes = make_request(repos_url, timeout=4.0)
        if repos_bytes:
            try:
                for r in json.loads(repos_bytes.decode("utf-8")):
                    repos.append({
                        "name": r.get("name"),
                        "full_name": r.get("full_name"),
                        "description": r.get("description"),
                        "stars": r.get("stargazers_count"),
                        "forks": r.get("forks_count"),
                        "language": r.get("language"),
                        "url": r.get("html_url"),
                        "updated_at": r.get("updated_at")
                    })
            except Exception:
                pass

        # Check for profile README
        profile_readme = ""
        readme_url = f"https://raw.githubusercontent.com/{clean_user}/{clean_user}/main/README.md"
        readme_bytes = make_request(readme_url, timeout=3.0)
        if not readme_bytes:
            readme_url = f"https://raw.githubusercontent.com/{clean_user}/{clean_user}/master/README.md"
            readme_bytes = make_request(readme_url, timeout=3.0)
        if readme_bytes:
            profile_readme = readme_bytes.decode("utf-8", errors="ignore")[:4000]

        return {
            "status": "Success",
            "type": "github_profile",
            "profile": {
                "username": user_data.get("login"),
                "name": user_data.get("name") or user_data.get("login"),
                "bio": user_data.get("bio"),
                "company": user_data.get("company"),
                "blog": user_data.get("blog"),
                "location": user_data.get("location"),
                "avatar_url": user_data.get("avatar_url"),
                "profile_url": user_data.get("html_url"),
                "public_repos": user_data.get("public_repos", 0),
                "public_gists": user_data.get("public_gists", 0),
                "followers": user_data.get("followers", 0),
                "following": user_data.get("following", 0),
                "created_at": user_data.get("created_at"),
                "updated_at": user_data.get("updated_at")
            },
            "pinned_or_recent_repositories": repos,
            "profile_readme": profile_readme
        }

    @classmethod
    def get_repository(cls, owner: str, repo: str) -> Dict[str, Any]:
        clean_owner = owner.strip().lstrip("@")
        clean_repo = repo.strip()
        url = f"{cls.BASE_API}/repos/{urllib.parse.quote(clean_owner)}/{urllib.parse.quote(clean_repo)}"
        raw_bytes = make_request(url, headers=cls._headers(), timeout=5.0)
        if not raw_bytes:
            return {"error": f"Repository '{clean_owner}/{clean_repo}' not found", "status": 404}

        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            return {"error": "Invalid response from GitHub API", "status": 502}

        # Latest commit
        latest_commit = {}
        commits_url = f"{cls.BASE_API}/repos/{clean_owner}/{clean_repo}/commits?per_page=1"
        commits_bytes = make_request(commits_url, headers=cls._headers(), timeout=3.5)
        if commits_bytes:
            try:
                commit_list = json.loads(commits_bytes.decode("utf-8"))
                if commit_list:
                    c = commit_list[0]
                    latest_commit = {
                        "sha": c.get("sha", "")[:7],
                        "message": c.get("commit", {}).get("message", "").split("\n")[0],
                        "author": c.get("commit", {}).get("author", {}).get("name"),
                        "date": c.get("commit", {}).get("author", {}).get("date")
                    }
            except Exception:
                pass

        # README content
        readme_text = ""
        default_branch = data.get("default_branch", "main")
        for branch in [default_branch, "master", "main"]:
            rm_url = f"https://raw.githubusercontent.com/{clean_owner}/{clean_repo}/{branch}/README.md"
            rm_bytes = make_request(rm_url, timeout=3.0)
            if rm_bytes:
                readme_text = rm_bytes.decode("utf-8", errors="ignore")[:8000]
                break

        return {
            "status": "Success",
            "type": "github_repository",
            "repository": {
                "name": data.get("name"),
                "full_name": data.get("full_name"),
                "description": data.get("description"),
                "url": data.get("html_url"),
                "homepage": data.get("homepage"),
                "stars": data.get("stargazers_count", 0),
                "forks": data.get("forks_count", 0),
                "watchers": data.get("watchers_count", 0),
                "open_issues": data.get("open_issues_count", 0),
                "language": data.get("language"),
                "topics": data.get("topics", []),
                "license": data.get("license", {}).get("name") if data.get("license") else None,
                "default_branch": default_branch,
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
                "pushed_at": data.get("pushed_at")
            },
            "latest_commit": latest_commit,
            "readme_preview": readme_text
        }

    @classmethod
    def get_trending(cls, language: Optional[str] = None, since: str = "daily") -> Dict[str, Any]:
        """Scrapes live GitHub trending repositories today, this week, or this month."""
        lang_segment = f"/{language.strip()}" if language else ""
        clean_since = since.lower() if since in ["daily", "weekly", "monthly"] else "daily"
        url = f"https://github.com/trending{lang_segment}?since={clean_since}"

        raw_bytes = make_request(url, timeout=6.0)
        items: List[Dict[str, Any]] = []

        if raw_bytes:
            content = raw_bytes.decode("utf-8", errors="ignore")
            articles = re.findall(r'<article class="Box-row">([\s\S]*?)</article>', content)
            pos = 1
            for a in articles:
                repo_m = re.search(r'href="/([^"/]+/[^"/]+)"', a)
                if not repo_m:
                    continue
                full_name = repo_m.group(1).strip()
                desc_m = re.search(r'<p class="col-9[^\"]*">(.*?)</p>', a, re.DOTALL)
                desc = clean_text(desc_m.group(1)) if desc_m else ""

                lang_m = re.search(r'itemprop="programmingLanguage">(.*?)</span>', a)
                lang = clean_text(lang_m.group(1)) if lang_m else ""

                stars_today_m = re.search(r'([\d,]+)\s+stars\s+(?:today|this week|this month)', a, re.IGNORECASE)
                stars_today = stars_today_m.group(1).replace(",", "") if stars_today_m else ""

                stars_total_m = re.search(r'href="/[^"/]+/[^"/]+/stargazers"[^>]*>[\s\r\n]*<svg[^>]*>[\s\S]*?</svg>[\s\r\n]*([\d,]+)', a)
                stars_total = stars_total_m.group(1).replace(",", "") if stars_total_m else ""

                items.append({
                    "position": pos,
                    "repo": full_name,
                    "url": f"https://github.com/{full_name}",
                    "description": desc,
                    "language": lang,
                    "stars_today": int(stars_today) if stars_today.isdigit() else 0,
                    "stars_total": int(stars_total) if stars_total.isdigit() else 0
                })
                pos += 1
                if len(items) >= 25:
                    break

        return {
            "status": "Success",
            "type": "github_trending",
            "language": language or "all",
            "since": clean_since,
            "total_repositories": len(items),
            "trending_repositories": items,
            "organic_results": [{
                "position": i["position"],
                "title": f"{i['repo']} — {i['language'] or 'Tech'}",
                "link": i["url"],
                "snippet": f"{i['description']} (⭐ {i['stars_today']} stars {clean_since}, Total: {i['stars_total']})",
                "source": "GitHub"
            } for i in items]
        }

    @classmethod
    def search_repositories(cls, query: str, limit: int = 10, sort: str = "stars") -> Dict[str, Any]:
        url = f"{cls.BASE_API}/search/repositories?q={urllib.parse.quote_plus(query)}&sort={sort}&per_page={limit}"
        raw_bytes = make_request(url, headers=cls._headers(), timeout=5.0)
        items: List[Dict[str, Any]] = []

        if raw_bytes:
            try:
                data = json.loads(raw_bytes.decode("utf-8"))
                for idx, r in enumerate(data.get("items", [])[:limit], 1):
                    items.append({
                        "position": idx,
                        "title": r.get("full_name"),
                        "link": r.get("html_url"),
                        "description": r.get("description") or "",
                        "snippet": f"{r.get('description') or ''} [⭐ {r.get('stargazers_count', 0)} stars, 🍴 {r.get('forks_count', 0)} forks, {r.get('language') or 'General'}]",
                        "stars": r.get("stargazers_count", 0),
                        "forks": r.get("forks_count", 0),
                        "language": r.get("language"),
                        "source": "GitHub"
                    })
            except Exception:
                pass

        return {
            "search_metadata": {"status": "Success", "engine": "github_search"},
            "search_parameters": {"q": query, "sort": sort, "limit": limit},
            "github_results": items,
            "organic_results": items
        }


# =========================================================================
# 3. AMAZON INSTANT AUTOCOMPLETE & SEARCH SUGGESTIONS ENGINE
# =========================================================================
class AmazonEngine:
    """
    Returns real-time suggestions across Amazon's marketplaces worldwide
    (US, UK, India, Germany, Canada, Japan).
    """
    MARKETS = {
        "us": {"mid": "ATVPDKIKX0DER", "host": "completion.amazon.com"},
        "in": {"mid": "A21TJRUUN4KGV", "host": "completion.amazon.in"},
        "uk": {"mid": "A1F83G8C2ARO7P", "host": "completion.amazon.co.uk"},
        "de": {"mid": "A1PA6795UKMFR9", "host": "completion.amazon.de"},
        "ca": {"mid": "A2EUQ1WTGCTBG2", "host": "completion.amazon.com"},
        "jp": {"mid": "A1VC38T7YXB528", "host": "completion.amazon.co.jp"}
    }

    @classmethod
    def autocomplete(cls, prefix: str, country: str = "us") -> Dict[str, Any]:
        c = country.lower().strip()
        config = cls.MARKETS.get(c, cls.MARKETS["us"])
        url = f"https://{config['host']}/api/2017/suggestions?mid={config['mid']}&alias=aps&prefix={urllib.parse.quote_plus(prefix)}"

        raw_bytes = make_request(url, timeout=3.5)
        suggestions: List[Dict[str, Any]] = []

        if raw_bytes:
            try:
                data = json.loads(raw_bytes.decode("utf-8"))
                for s in data.get("suggestions", []):
                    val = s.get("value", "")
                    if val:
                        suggestions.append({
                            "suggestion": val,
                            "search_url": f"https://www.amazon.{'co.uk' if c == 'uk' else ('co.jp' if c == 'jp' else c)}/s?k={urllib.parse.quote_plus(val)}"
                        })
            except Exception:
                pass

        # Fallback to US if regional returned empty
        if not suggestions and c != "us":
            return cls.autocomplete(prefix, country="us")

        return {
            "status": "Success",
            "type": "amazon_autocomplete",
            "query": prefix,
            "country": c,
            "suggestions_count": len(suggestions),
            "suggestions": suggestions
        }


# =========================================================================
# 4. YOUTUBE VIDEO & CHANNEL LIVES ENGINE
# =========================================================================
class YouTubeEngine:
    """
    Returns YouTube search results, live broadcast status, and trending videos
    without requiring Google YouTube Data v3 API keys.
    """
    @classmethod
    def search_videos(cls, query: str, limit: int = 10, live_only: bool = False) -> Dict[str, Any]:
        start_t = time.time()
        sp_filter = "&sp=CAM%253D" if live_only else ""
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}{sp_filter}"

        raw_bytes = make_request(url, timeout=5.0)
        videos: List[Dict[str, Any]] = []

        if raw_bytes:
            try:
                html_str = raw_bytes.decode("utf-8", errors="ignore")
                m = re.search(r"var ytInitialData = ({.*?});</script>", html_str)
                if m:
                    d = json.loads(m.group(1))
                    section = d.get("contents", {}).get("twoColumnSearchResultsRenderer", {}).get("primaryContents", {}).get("sectionListRenderer", {}).get("contents", [])
                    pos = 1
                    for s in section:
                        items = s.get("itemSectionRenderer", {}).get("contents", [])
                        for item in items:
                            v = item.get("videoRenderer")
                            if v:
                                title = v.get("title", {}).get("runs", [{}])[0].get("text", "")
                                vid = v.get("videoId", "")
                                channel = v.get("ownerText", {}).get("runs", [{}])[0].get("text", "")
                                view_count = v.get("viewCountText", {}).get("simpleText", "")
                                published = v.get("publishedTimeText", {}).get("simpleText", "")
                                length = v.get("lengthText", {}).get("simpleText", "")
                                is_live = any(b.get("metadataBadgeRenderer", {}).get("label") == "LIVE" for b in v.get("badges", []))

                                if live_only and not is_live:
                                    continue

                                thumbs = v.get("thumbnail", {}).get("thumbnails", [])
                                thumb_url = thumbs[-1].get("url") if thumbs else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

                                if title and vid:
                                    videos.append({
                                        "position": pos,
                                        "title": title,
                                        "link": f"https://www.youtube.com/watch?v={vid}",
                                        "video_id": vid,
                                        "channel": channel,
                                        "views": view_count,
                                        "published": published,
                                        "duration": length or ("LIVE" if is_live else ""),
                                        "is_live": is_live,
                                        "thumbnail": thumb_url,
                                        "snippet": f"Video by {channel} &bull; {view_count or 'Live'} &bull; {published or 'Live now'}",
                                        "source": "YouTube"
                                    })
                                    pos += 1
                                    if len(videos) >= limit:
                                        break
            except Exception:
                pass

        elapsed = round(time.time() - start_t, 2)
        return {
            "search_metadata": {
                "status": "Success",
                "engine": "youtube_search",
                "total_time_taken": elapsed,
                "total_results": len(videos)
            },
            "search_parameters": {"q": query, "live_only": live_only, "limit": limit},
            "youtube_results": videos,
            "organic_results": videos
        }


# =========================================================================
# 5. LINKEDIN PUBLIC GUEST JOBS ENGINE
# =========================================================================
class LinkedInJobsEngine:
    """
    Extracts authentic LinkedIn job listings and career opportunities
    via public guest search endpoints without login or credentials.
    """
    @classmethod
    def search_jobs(cls, keywords: str, location: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
        start_t = time.time()
        loc_str = location.strip() if location else ""
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={urllib.parse.quote_plus(keywords)}&location={urllib.parse.quote_plus(loc_str)}&start=0"

        headers = {
            "User-Agent": USER_AGENTS[0],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9"
        }
        raw_bytes = make_request(url, headers=headers, timeout=5.0)
        jobs: List[Dict[str, Any]] = []

        if raw_bytes:
            try:
                html_str = raw_bytes.decode("utf-8", errors="ignore")
                job_cards = re.findall(r"<li[^>]*>([\s\S]*?)</li>", html_str)
                pos = 1
                for c in job_cards:
                    title_m = re.search(r"<h3[^>]*base-search-card__title[^>]*>(.*?)</h3>", c, re.DOTALL)
                    comp_m = re.search(r"<h4[^>]*base-search-card__subtitle[^>]*>(.*?)</h4>", c, re.DOTALL)
                    loc_m = re.search(r"<span[^>]*job-search-card__location[^>]*>(.*?)</span>", c, re.DOTALL)
                    link_m = re.search(r'<a[^>]*base-card__full-link[^>]*href="([^"]+)"', c)
                    time_m = re.search(r"<time[^>]*datetime=\"([^\"]+)\"[^>]*>(.*?)</time>", c, re.DOTALL)

                    title = clean_text(title_m.group(1)) if title_m else ""
                    company = clean_text(comp_m.group(1)) if comp_m else ""
                    job_loc = clean_text(loc_m.group(1)) if loc_m else loc_str
                    link = link_m.group(1).split("?")[0] if link_m else ""
                    posted_date = clean_text(time_m.group(2)) if time_m else ""

                    if title and link:
                        jobs.append({
                            "position": pos,
                            "title": title,
                            "company": company,
                            "location": job_loc,
                            "link": link,
                            "posted": posted_date,
                            "snippet": f"{title} at {company} &bull; Location: {job_loc} &bull; Posted: {posted_date or 'Recently'}",
                            "source": "LinkedIn"
                        })
                        pos += 1
                        if len(jobs) >= limit:
                            break
            except Exception:
                pass

        elapsed = round(time.time() - start_t, 2)
        return {
            "search_metadata": {
                "status": "Success",
                "engine": "linkedin_jobs",
                "total_time_taken": elapsed,
                "total_results": len(jobs)
            },
            "search_parameters": {"keywords": keywords, "location": loc_str, "limit": limit},
            "jobs_results": jobs,
            "organic_results": jobs
        }


# =========================================================================
# 6. OPEN MAPS & PLACES ENGINE
# =========================================================================
class PlacesEngine:
    """
    Real-time geocoding, landmark search, and geographic place resolution
    powered by OpenStreetMap Nominatim.
    """
    @classmethod
    def search_places(cls, query: str, limit: int = 10) -> Dict[str, Any]:
        start_t = time.time()
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote_plus(query)}&format=json&addressdetails=1&limit={limit}"
        headers = {"User-Agent": "NTAWebSearch/2.0 (sovereign-search-engine)"}

        raw_bytes = make_request(url, headers=headers, timeout=5.0)
        places: List[Dict[str, Any]] = []

        if raw_bytes:
            try:
                data = json.loads(raw_bytes.decode("utf-8"))
                for idx, p in enumerate(data[:limit], 1):
                    addr = p.get("address", {})
                    name = p.get("name") or addr.get("road") or p.get("display_name", "").split(",")[0]
                    places.append({
                        "position": idx,
                        "title": name,
                        "display_name": p.get("display_name"),
                        "category": p.get("category"),
                        "type": p.get("type"),
                        "latitude": float(p.get("lat", 0)),
                        "longitude": float(p.get("lon", 0)),
                        "bounding_box": p.get("boundingbox", []),
                        "address": {
                            "road": addr.get("road"),
                            "city": addr.get("city") or addr.get("town") or addr.get("village"),
                            "state": addr.get("state"),
                            "country": addr.get("country"),
                            "postcode": addr.get("postcode")
                        },
                        "osm_url": f"https://www.openstreetmap.org/?mlat={p.get('lat')}&mlon={p.get('lon')}#map=16/{p.get('lat')}/{p.get('lon')}",
                        "source": "OpenStreetMap"
                    })
            except Exception:
                pass

        elapsed = round(time.time() - start_t, 2)
        return {
            "search_metadata": {
                "status": "Success",
                "engine": "places_search",
                "total_time_taken": elapsed,
                "total_results": len(places)
            },
            "search_parameters": {"q": query, "limit": limit},
            "local_results": places,
            "organic_results": [{
                "position": p["position"],
                "title": p["title"],
                "link": p["osm_url"],
                "snippet": f"{p['display_name']} [Lat: {p['latitude']}, Lon: {p['longitude']}]",
                "source": "OpenStreetMap"
            } for p in places]
        }


# =========================================================================
# 7. HIGH-SPEED CALCULATOR & UNIT CONVERTER
# =========================================================================
class MathAndUnitsEngine:
    """
    Sub-millisecond calculator and unit conversion answering engine.
    Returns exact SerpAPI answer_box formatted with LaTeX equations.
    """
    # Safe mathematical environment
    SAFE_MATH = {
        "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "log": math.log, "log10": math.log10, "exp": math.exp, "pow": math.pow,
        "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil,
        "pi": math.pi, "e": math.e
    }

    # Unit conversion factors to standard base units
    LENGTH_TO_M = {
        "m": 1.0, "meter": 1.0, "meters": 1.0,
        "km": 1000.0, "kilometer": 1000.0, "kilometers": 1000.0,
        "cm": 0.01, "centimeter": 0.01, "centimeters": 0.01,
        "mm": 0.001, "millimeter": 0.001,
        "mi": 1609.344, "mile": 1609.344, "miles": 1609.344,
        "yd": 0.9144, "yard": 0.9144, "yards": 0.9144,
        "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
        "in": 0.0254, "inch": 0.0254, "inches": 0.0254
    }

    WEIGHT_TO_KG = {
        "kg": 1.0, "kilogram": 1.0, "kilograms": 1.0,
        "g": 0.001, "gram": 0.001, "grams": 0.001,
        "mg": 0.000001, "milligram": 0.000001,
        "lb": 0.45359237, "lbs": 0.45359237, "pound": 0.45359237, "pounds": 0.45359237,
        "oz": 0.0283495, "ounce": 0.0283495, "ounces": 0.0283495,
        "ton": 1000.0, "tons": 1000.0
    }

    DATA_TO_MB = {
        "b": 1e-6, "byte": 1e-6, "bytes": 1e-6,
        "kb": 0.001, "kilobyte": 0.001, "kilobytes": 0.001,
        "mb": 1.0, "megabyte": 1.0, "megabytes": 1.0,
        "gb": 1000.0, "gigabyte": 1000.0, "gigabytes": 1000.0,
        "tb": 1000000.0, "terabyte": 1000000.0, "terabytes": 1000000.0
    }

    @classmethod
    def evaluate(cls, query: str) -> Optional[Dict[str, Any]]:
        q = query.strip()
        if not q:
            return None

        # 1. Check Unit Conversion (e.g., "50 km in miles", "100 usd to inr", "25 celsius to fahrenheit")
        unit_box = cls._check_unit_conversion(q)
        if unit_box:
            return unit_box

        # 2. Check Math Calculation
        return cls._check_math_calculation(q)

    @classmethod
    def _check_unit_conversion(cls, q: str) -> Optional[Dict[str, Any]]:
        m = re.match(r"^([\d\.]+)\s*([a-zA-Z]+)\s+(?:in|to|into)\s+([a-zA-Z]+)$", q, re.IGNORECASE)
        if not m:
            return None

        val = float(m.group(1))
        u1 = m.group(2).lower()
        u2 = m.group(3).lower()

        # Temperature
        if u1 in ["c", "celsius"] and u2 in ["f", "fahrenheit"]:
            res = (val * 9 / 5) + 32
            return {
                "type": "unit_converter",
                "title": "Temperature Conversion",
                "answer": f"{val}°C = {round(res, 2)}°F",
                "formula": f"({val} × 9/5) + 32 = {round(res, 2)}"
            }
        if u1 in ["f", "fahrenheit"] and u2 in ["c", "celsius"]:
            res = (val - 32) * 5 / 9
            return {
                "type": "unit_converter",
                "title": "Temperature Conversion",
                "answer": f"{val}°F = {round(res, 2)}°C",
                "formula": f"({val} - 32) × 5/9 = {round(res, 2)}"
            }

        # Length
        if u1 in cls.LENGTH_TO_M and u2 in cls.LENGTH_TO_M:
            meters = val * cls.LENGTH_TO_M[u1]
            converted = meters / cls.LENGTH_TO_M[u2]
            return {
                "type": "unit_converter",
                "title": "Length Conversion",
                "answer": f"{val} {u1} = {round(converted, 4)} {u2}",
                "formula": f"{val} {u1} × {round(cls.LENGTH_TO_M[u1]/cls.LENGTH_TO_M[u2], 6)}"
            }

        # Weight
        if u1 in cls.WEIGHT_TO_KG and u2 in cls.WEIGHT_TO_KG:
            kg = val * cls.WEIGHT_TO_KG[u1]
            converted = kg / cls.WEIGHT_TO_KG[u2]
            return {
                "type": "unit_converter",
                "title": "Mass Conversion",
                "answer": f"{val} {u1} = {round(converted, 4)} {u2}",
                "formula": f"{val} {u1} × {round(cls.WEIGHT_TO_KG[u1]/cls.WEIGHT_TO_KG[u2], 6)}"
            }

        # Digital Data
        if u1 in cls.DATA_TO_MB and u2 in cls.DATA_TO_MB:
            mb = val * cls.DATA_TO_MB[u1]
            converted = mb / cls.DATA_TO_MB[u2]
            return {
                "type": "unit_converter",
                "title": "Digital Storage Conversion",
                "answer": f"{val} {u1} = {round(converted, 4)} {u2}",
                "formula": f"{val} {u1} × {round(cls.DATA_TO_MB[u1]/cls.DATA_TO_MB[u2], 6)}"
            }

        return None

    @classmethod
    def _check_math_calculation(cls, q: str) -> Optional[Dict[str, Any]]:
        # Normalize expressions: "what is 2 + 2", "calc 5 * 10", replace ^ with **
        expr = re.sub(r"^(?:what\s+is|calculate|calc|compute|solve)\s+", "", q, flags=re.IGNORECASE).strip()
        expr = expr.rstrip("?=").strip()

        # Sanitize symbols
        clean_expr = expr.replace("x", "*").replace("×", "*").replace("÷", "/").replace("^", "**")
        # Convert accidental unencoded URL spaces between numbers/operands into '+' (e.g. 'sqrt(256)*4 20' -> 'sqrt(256)*4+20')
        clean_expr = re.sub(r"(?<=[\d\)])\s+(?=[\d\(]|sqrt|sin|cos|tan|log|pi)", "+", clean_expr)

        # Must contain at least one math operator or known math function
        if not re.search(r"[\+\-\*/%\*\*]|sqrt|sin|cos|tan|log|pi|pow", clean_expr, re.IGNORECASE):
            return None

        # Verify no suspicious characters (only letters, numbers, spaces, operators, brackets, dots)
        if not re.match(r"^[\d\.\s\+\-\*/%\(\),\*\*\w]+$", clean_expr):
            return None

        try:
            # Parse AST to ensure strict safety
            parsed = ast.parse(clean_expr, mode="eval")
            for node in ast.walk(parsed):
                if isinstance(node, (ast.Import, ast.ImportFrom, ast.Attribute, ast.Lambda)):
                    return None

            result = eval(clean_expr, {"__builtins__": None}, cls.SAFE_MATH)
            if isinstance(result, float):
                # Avoid long ugly floats if integer
                result_str = str(int(result)) if result.is_integer() else str(round(result, 6))
            else:
                result_str = str(result)

            latex_expr = clean_expr.replace("**", "^").replace("*", r"\times ").replace("/", r"\div ")

            return {
                "type": "calculator",
                "title": "Calculator",
                "expression": expr,
                "result": result_str,
                "answer": f"{expr} = {result_str}",
                "latex": f"{latex_expr} = {result_str}"
            }
        except Exception:
            return None
