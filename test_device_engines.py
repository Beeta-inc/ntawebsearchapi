import sys
from extended_engines import (
    RedditEngine, GitHubEngine, AmazonEngine, YouTubeEngine,
    LinkedInJobsEngine, PlacesEngine, MathAndUnitsEngine
)

print("--- 1. MATH / CALC ---")
print(MathAndUnitsEngine.evaluate("sqrt(256) * 4 + 20"))
print(MathAndUnitsEngine.evaluate("100 miles to km"))

print("\n--- 2. AMAZON AUTOCOMPLETE ---")
print(AmazonEngine.autocomplete("macbook")["suggestions"][:3])

print("\n--- 3. GITHUB REPOSITORIES ---")
print(GitHubEngine.search_repositories("torvalds", limit=3))

print("\n--- 4. REDDIT SEARCH ---")
print(RedditEngine.search("mechanical keyboards", limit=3))

print("\n--- 5. PLACES ---")
print(PlacesEngine.search_places("Tokyo Tower", limit=1)["local_results"])
