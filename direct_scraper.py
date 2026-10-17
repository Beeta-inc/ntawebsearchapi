import re
import time
import json
import urllib.request
import urllib.parse
import gzip
import io
import concurrent.futures
from typing import List, Dict, Any, Tuple, Optional

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0"
]

STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "as", "at",
    "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can", "did", "do",
    "does", "doing", "down", "during", "each", "for", "from", "further", "had", "has", "have", "having", "he",
    "her", "here", "hers", "him", "his", "how", "i", "if", "in", "into", "is", "it", "its", "me", "more", "most",
    "my", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "our", "ours", "out", "over",
    "own", "same", "she", "should", "so", "some", "such", "than", "that", "the", "their", "theirs", "them",
    "then", "there", "these", "they", "this", "those", "through", "to", "too", "under", "until", "up", "very",
    "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why", "with", "you", "your"
}

def make_http_request(url: str, timeout: float = 5.0) -> Optional[str]:
    try:
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url
        headers = {
            "User-Agent": USER_AGENTS[int(time.time()) % len(USER_AGENTS)],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Cache-Control": "no-cache"
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            if resp.info().get('Content-Encoding') == 'gzip':
                try:
                    data = gzip.decompress(data)
                except Exception:
                    pass
            return data.decode('utf-8', errors='ignore')
    except Exception:
        return None

def clean_html(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r'<!\[CDATA\[|\]\]>', '', html)
    text = re.sub(r'<[^>]*>', ' ', text)
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    return re.sub(r'\s+', ' ', text).strip()

class MultiEngineFallbackSearch:
    """
    Sub-second multi-engine search aggregator inspired by NetuarkAiSearchEngine.kt.
    Aggregates DuckDuckGo, Yahoo, Google HTML, Wikipedia, and Google News RSS.
    """
    make_http_request = staticmethod(make_http_request)
    clean_html = staticmethod(clean_html)
    def search_duckduckgo(self, query: str) -> List[Dict[str, str]]:
        results = []
        try:
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}"
            html = make_http_request(url, timeout=4.0)
            if html:
                for match in re.finditer(r'<a class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>[\s\S]*?<a class="result__snippet"[^>]*>([\s\S]*?)</a>', html):
                    raw_url = match.group(1)
                    title = clean_html(match.group(2))
                    snippet = clean_html(match.group(3))

                    final_url = raw_url
                    if "uddg=" in raw_url:
                        try:
                            encoded_target = raw_url.split("uddg=")[1].split("&")[0]
                            final_url = urllib.parse.unquote(encoded_target)
                        except Exception:
                            final_url = raw_url

                    if title and final_url and snippet:
                        results.append({
                            "title": title,
                            "link": final_url,
                            "snippet": snippet,
                            "source": urllib.parse.urlparse(final_url).hostname or "duckduckgo"
                        })
                    if len(results) >= 8:
                        break
        except Exception:
            pass
        return results

    def search_yahoo(self, query: str) -> List[Dict[str, str]]:
        results = []
        try:
            url = f"https://search.yahoo.com/search?p={urllib.parse.quote_plus(query)}"
            html = make_http_request(url, timeout=4.0)
            if html:
                for match in re.finditer(r'<div class="[^"]*algo[^"]*"[\s\S]*?<h3[^>]*>([\s\S]*?)</h3>[\s\S]*?RU=(https%3a%2f%2f[^\s&"]+|https%3A%2F%2F[^\s&"]+)[\s\S]*?<div class="compText[^"]*"[^>]*>([\s\S]*?)</div>', html, re.IGNORECASE):
                    title = clean_html(match.group(1))
                    raw_url = match.group(2).split("/RK=")[0].split("/RS=")[0]
                    desc = clean_html(match.group(3))
                    try:
                        final_url = urllib.parse.unquote(raw_url)
                    except Exception:
                        final_url = ""

                    if title and final_url and not "yahoo." in final_url:
                        results.append({
                            "title": title,
                            "link": final_url,
                            "snippet": desc,
                            "source": urllib.parse.urlparse(final_url).hostname or "yahoo"
                        })
                    if len(results) >= 8:
                        break
        except Exception:
            pass
        return results

    def search_wikipedia(self, query: str) -> List[Dict[str, str]]:
        results = []
        try:
            url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={urllib.parse.quote_plus(query)}&utf8=&format=json"
            raw = make_http_request(url, timeout=3.5)
            if raw:
                data = json.loads(raw)
                items = data.get("query", {}).get("search", [])[:3]
                for item in items:
                    title = item.get("title", "")
                    snippet = clean_html(item.get("snippet", ""))
                    link = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
                    results.append({
                        "title": f"Wikipedia: {title}",
                        "link": link,
                        "snippet": snippet,
                        "source": "en.wikipedia.org"
                    })
        except Exception:
            pass
        return results

    def search_news_rss(self, query: str) -> List[Dict[str, str]]:
        results = []
        try:
            url = f"https://news.google.com/rss/search?q={urllib.parse.quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
            xml = make_http_request(url, timeout=3.5)
            if xml:
                for match in re.finditer(r'<item>[\s\S]*?<title>(.*?)</title>[\s\S]*?<link>(.*?)</link>[\s\S]*?<description>(.*?)</description>', xml):
                    title = clean_html(match.group(1))
                    link = match.group(2).strip()
                    desc = clean_html(match.group(3))
                    if title and link:
                        results.append({
                            "title": title,
                            "link": link,
                            "snippet": desc,
                            "source": "news.google.com"
                        })
                    if len(results) >= 5:
                        break
        except Exception:
            pass
        return results

    def execute_multi_search(self, query: str, num: int = 10) -> Dict[str, Any]:
        start_t = time.time()
        combined = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            f_ddg = executor.submit(self.search_duckduckgo, query)
            f_yah = executor.submit(self.search_yahoo, query)
            f_wiki = executor.submit(self.search_wikipedia, query)
            f_news = executor.submit(self.search_news_rss, query)

            for f in [f_ddg, f_yah, f_wiki, f_news]:
                try:
                    combined.extend(f.result(timeout=4.5))
                except Exception:
                    pass

        # Deduplicate results by URL
        seen_urls = set()
        unique_results = []
        pos = 1
        for item in combined:
            url = item.get("link", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                item["position"] = pos
                pos += 1
                unique_results.append(item)
            if len(unique_results) >= num:
                break

        elapsed = round(time.time() - start_t, 2)
        return {
            "search_metadata": {
                "status": "Success",
                "total_time_taken": elapsed,
                "engine": "sovereign_multi_fallback_engine"
            },
            "search_parameters": {
                "q": query,
                "engine": "google"
            },
            "organic_results": unique_results
        }

    def build_ai_observation(self, organic_results: List[Dict[str, Any]], max_words: int = 2500) -> str:
        """Constructs an LLM-ready context block formatted for ReAct agents."""
        obs = []
        total_words = 0
        for r in organic_results:
            title = r.get("title", "Untitled")
            link = r.get("link", "")
            snippet = r.get("snippet", "")
            chunk = f"--- [Source #{r.get('position', 1)} | {title} | URL: {link}] ---\n{snippet}\n\n"
            words = len(chunk.split())
            if total_words + words > max_words:
                break
            obs.append(chunk)
            total_words += words
        return "".join(obs)

# Global singleton
direct_search_engine = MultiEngineFallbackSearch()
