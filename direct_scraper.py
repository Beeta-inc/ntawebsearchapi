import re
import time
import json
import html
import urllib.request
import urllib.parse
import gzip
import io
import concurrent.futures
from typing import List, Dict, Any, Tuple, Optional

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
]

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

def clean_html(raw: str) -> str:
    """Thoroughly strips HTML tags and unescapes entities."""
    if not raw:
        return ""
    text = re.sub(r'<!\[CDATA\[|\]\]>', '', raw)
    text = html.unescape(text)
    text = re.sub(r'<[^>]*>', ' ', text)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


class MultiEngineFallbackSearch:
    """
    Sub-second multi-engine search aggregator inspired by NetuarkAiSearchEngine.kt.
    Aggregates Wikipedia OpenSearch, Google Suggest, and cleaned Google News RSS.
    """
    make_http_request = staticmethod(make_http_request)
    clean_html = staticmethod(clean_html)

    def search_wikipedia_opensearch(self, query: str) -> List[Dict[str, str]]:
        results = []
        try:
            url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={urllib.parse.quote_plus(query)}&limit=5&namespace=0&format=json"
            raw = make_http_request(url, timeout=3.5)
            if raw:
                data = json.loads(raw)
                if len(data) >= 4:
                    titles = data[1]
                    descriptions = data[2]
                    links = data[3]
                    for t, d, l in zip(titles, descriptions, links):
                        if t and l:
                            results.append({
                                "title": f"Wikipedia: {t}",
                                "link": l,
                                "snippet": clean_html(d or f"Information regarding {t} on Wikipedia encyclopedia."),
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
                    # Remove the source publisher suffix if repeated in snippet
                    if title and link:
                        results.append({
                            "title": title,
                            "link": link,
                            "snippet": desc,
                            "source": "news.google.com"
                        })
                    if len(results) >= 4:
                        break
        except Exception:
            pass
        return results

    def get_related_searches(self, query: str) -> List[Dict[str, str]]:
        related = []
        try:
            url = f"https://suggestqueries.google.com/complete/search?client=firefox&q={urllib.parse.quote_plus(query)}"
            raw = make_http_request(url, timeout=2.5)
            if raw:
                data = json.loads(raw)
                if len(data) >= 2 and isinstance(data[1], list):
                    for item in data[1][:8]:
                        if item and item.lower() != query.lower():
                            related.append({"query": str(item)})
        except Exception:
            pass
        return related

    def execute_multi_search(self, query: str, num: int = 10) -> Dict[str, Any]:
        start_t = time.time()
        combined = []
        related = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            f_wiki = executor.submit(self.search_wikipedia_opensearch, query)
            f_news = executor.submit(self.search_news_rss, query)
            f_sug = executor.submit(self.get_related_searches, query)

            try:
                combined.extend(f_wiki.result(timeout=4.0))
            except Exception:
                pass

            try:
                combined.extend(f_news.result(timeout=4.0))
            except Exception:
                pass

            try:
                related = f_sug.result(timeout=3.0)
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
                "id": f"search_fallback_{int(time.time()*1000)}",
                "status": "Success",
                "total_time_taken": elapsed,
                "engine": "sovereign_multi_fallback_engine",
                "device": "Lenovo L38012 (Termux aarch64)"
            },
            "search_parameters": {
                "q": query,
                "engine": "google"
            },
            "organic_results": unique_results,
            "related_searches": related
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


# Global singleton instance
direct_search_engine = MultiEngineFallbackSearch()
