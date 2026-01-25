#!/usr/bin/env python3
"""Ketochef recipe scraper for https://ketochef.co.il/recipes.

Steps implemented:
1) Fetch the listing page and discover recipe links from the HTML document.
2) Traverse pagination links to gather recipe URLs from listing pages only.
3) Write the collected recipe URLs to a UTF-8 CSV (URL-encoded).
"""

from __future__ import annotations

import csv
import sys
from html.parser import HTMLParser
from typing import Iterable, List, Optional, Set
from urllib.parse import quote, urljoin, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen

BASE_URL = "https://ketochef.co.il/"
RECIPES_URL = "https://ketochef.co.il/recipes"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_1) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/116.0.0.0 Safari/537.36"
)


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        if tag != "a":
            return
        for key, value in attrs:
            if key == "href" and value:
                self.links.append(value)


def fetch_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def is_recipe_link(link: str) -> bool:
    parsed = urlparse(link)
    if parsed.netloc and parsed.netloc != urlparse(BASE_URL).netloc:
        return False
    path = parsed.path.rstrip("/")
    if path == "/recipes":
        return False
    if path.startswith("/recipes/page/") or (path.startswith("/recipes") and "page=" in parsed.query):
        return False
    return path.startswith("/recipe") or path.startswith("/recipes/")


def is_listing_page(link: str) -> bool:
    parsed = urlparse(link)
    if parsed.netloc and parsed.netloc != urlparse(BASE_URL).netloc:
        return False
    path = parsed.path.rstrip("/")
    return path.startswith("/recipes") and ("/page/" in path or "page=" in parsed.query)


def normalize_url(link: str) -> str:
    absolute = urljoin(BASE_URL, link)
    parts = urlsplit(absolute)
    safe_path = quote(parts.path, safe="/%")
    safe_query = quote(parts.query, safe="=&%")
    safe_fragment = quote(parts.fragment, safe="")
    return urlunsplit((parts.scheme, parts.netloc, safe_path, safe_query, safe_fragment))


def normalize_links(links: Iterable[str]) -> Set[str]:
    normalized = set()
    for link in links:
        absolute = normalize_url(link)
        if is_recipe_link(absolute):
            normalized.add(absolute)
    return normalized


def extract_recipe_links(listing_html: str) -> Set[str]:
    parser = LinkParser()
    parser.feed(listing_html)
    return normalize_links(parser.links)


def extract_listing_pages(listing_html: str) -> Set[str]:
    parser = LinkParser()
    parser.feed(listing_html)
    listing_pages = set()
    for link in parser.links:
        absolute = normalize_url(link)
        if is_listing_page(absolute):
            listing_pages.add(absolute)
    return listing_pages


def collect_recipe_links(start_url: str) -> Set[str]:
    listing_html = fetch_html(start_url)
    listing_pages = extract_listing_pages(listing_html) | {start_url}
    recipe_links: Set[str] = set()
    for page_url in sorted(listing_pages):
        page_html = listing_html if page_url == start_url else fetch_html(page_url)
        recipe_links.update(extract_recipe_links(page_html))
    return recipe_links


def write_csv(urls: Iterable[str], output_path: str) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["url"])
        for url in sorted(urls):
            writer.writerow([url])


def main() -> int:
    print("Step 1: Fetch listing page and discover structure...")
    print(f"Fetching {RECIPES_URL}")
    recipe_links = collect_recipe_links(RECIPES_URL)
    print(f"Found {len(recipe_links)} recipe link(s).")

    output_path = "recipes.csv"
    write_csv(recipe_links, output_path)
    print(f"Wrote {len(recipe_links)} recipe URLs to {output_path}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
