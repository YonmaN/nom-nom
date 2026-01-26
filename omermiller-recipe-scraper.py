#!/usr/bin/env python3
"""Recipe URL scraper for https://omermiller.co.il/category/מתכונים/.

Steps implemented:
1) Fetch the listing page and discover recipe links from the HTML document.
2) Traverse pagination links to gather recipe URLs from listing pages only.
3) Write the recipe URLs to a UTF-8 CSV (not URL-encoded).
"""

from __future__ import annotations

import argparse
import csv
from html.parser import HTMLParser
from typing import Iterable, List, Optional, Set
from urllib.parse import ParseResult, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

BASE_URL = "https://omermiller.co.il/"
CATEGORY_URL = "https://omermiller.co.il/category/%D7%9E%D7%AA%D7%9B%D7%95%D7%A0%D7%99%D7%9D/"
CATEGORY_PATH = unquote(urlparse(CATEGORY_URL).path)
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


def is_same_domain(parsed: ParseResult, base_url: str) -> bool:
    return parsed.netloc in {"", urlparse(base_url).netloc}


def normalize_category_path(category_path: str) -> str:
    normalized = unquote(category_path).rstrip("/")
    return normalized if normalized.startswith("/") else f"/{normalized}"


def is_category_root(path: str, category_path: str) -> bool:
    normalized_path = unquote(path).rstrip("/")
    normalized_category = normalize_category_path(category_path)
    return normalized_path == normalized_category


def is_pagination_link(parsed: ParseResult, category_path: str) -> bool:
    normalized_category = normalize_category_path(category_path)
    normalized_path = unquote(parsed.path).rstrip("/")
    if parsed.query and "paged=" in parsed.query:
        return True
    return normalized_path.startswith(f"{normalized_category}/page/")


def is_recipe_link(url: str, base_url: str, category_path: str) -> bool:
    parsed = urlparse(url)
    if not is_same_domain(parsed, base_url):
        return False
    path = unquote(parsed.path).rstrip("/")
    if not path or path == "/":
        return False
    if is_category_root(path, category_path):
        return False
    if is_pagination_link(parsed, category_path):
        return False
    if path.startswith("/category/") or path.startswith("/tag/"):
        return False
    if path.startswith("/wp-"):
        return False
    return True


def is_listing_page(url: str, base_url: str, category_path: str) -> bool:
    parsed = urlparse(url)
    if not is_same_domain(parsed, base_url):
        return False
    return is_pagination_link(parsed, category_path)


def extract_links(html: str) -> List[str]:
    parser = LinkParser()
    parser.feed(html)
    return parser.links


def extract_recipe_links(
    listing_html: str,
    base_url: str = BASE_URL,
    category_path: str = CATEGORY_PATH,
) -> Set[str]:
    links = extract_links(listing_html)
    recipes = set()
    for link in links:
        absolute = urljoin(base_url, link)
        if is_recipe_link(absolute, base_url, category_path):
            recipes.add(unquote(absolute))
    return recipes


def extract_listing_pages(
    listing_html: str,
    base_url: str = BASE_URL,
    category_path: str = CATEGORY_PATH,
) -> Set[str]:
    links = extract_links(listing_html)
    pages = set()
    for link in links:
        absolute = urljoin(base_url, link)
        if is_listing_page(absolute, base_url, category_path):
            pages.add(absolute)
    return pages


def collect_all_recipe_links(
    start_url: str,
    base_url: str = BASE_URL,
    category_path: str = CATEGORY_PATH,
) -> Set[str]:
    to_visit = [start_url]
    visited = set()
    recipes = set()
    while to_visit:
        current = to_visit.pop()
        if current in visited:
            continue
        visited.add(current)
        html = fetch_html(current)
        recipes.update(extract_recipe_links(html, base_url=base_url, category_path=category_path))
        for page in extract_listing_pages(html, base_url=base_url, category_path=category_path):
            if page not in visited:
                to_visit.append(page)
    return recipes


def write_csv(urls: Iterable[str], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["url"])
        for url in sorted(set(urls)):
            writer.writerow([url])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape recipe URLs from Omer Miller.")
    parser.add_argument(
        "--output",
        default="omermiller_recipes.csv",
        help="Path to the UTF-8 CSV file to write.",
    )
    parser.add_argument(
        "--start-url",
        default=CATEGORY_URL,
        help="Listing page URL to start crawling.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    urls = collect_all_recipe_links(args.start_url)
    write_csv(urls, args.output)


if __name__ == "__main__":
    main()
