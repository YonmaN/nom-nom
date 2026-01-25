#!/usr/bin/env python3
"""Ketochef recipe scraper for https://ketochef.co.il/recipes.

Steps implemented:
1) Fetch the listing page and discover recipe links from the HTML document.
2) Traverse pagination links to gather recipe URLs from listing pages only.
3) Fetch each recipe page and extract the name, ingredients, and steps.
4) Write the collected recipe data to a UTF-8 CSV (URL-encoded).
"""

from __future__ import annotations

import csv
import sys
from html.parser import HTMLParser
from dataclasses import dataclass
from typing import Iterable, List, Optional, Set
from urllib.parse import quote, unquote, urljoin, urlparse, urlsplit, urlunsplit
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


@dataclass
class RecipeData:
    url: str
    name: str
    ingredients: List[str]
    steps: List[str]


class RecipeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: List[str] = []
        self.ingredients: List[str] = []
        self.steps: List[str] = []
        self._ingredient_buffer: List[str] = []
        self._step_buffer: List[str] = []
        self._heading_buffer: List[str] = []
        self._heading_tag: Optional[str] = None
        self._in_title = False
        self._ingredient_depth = 0
        self._step_depth = 0
        self._in_ingredient_item = False
        self._in_step_item = False
        self._ignore_depth = 0
        self._tag_depth = 0
        self._content_depth = 0
        self._section: Optional[str] = None
        self._section_depth: Optional[int] = None

    @staticmethod
    def _is_ingredient_heading(text: str) -> bool:
        lowered = text.lower()
        normalized = lowered.replace(":", "").strip()
        return "ingredient" in normalized or "מצרכ" in normalized or "רכיב" in normalized

    @staticmethod
    def _is_step_heading(text: str) -> bool:
        lowered = text.lower()
        normalized = lowered.replace(":", "").strip()
        return (
            "instruction" in normalized
            or "direction" in normalized
            or "step" in normalized
            or "אופן הכנה" in normalized
            or "הכנה" in normalized
            or "הוראות הכנה" in normalized
            or "הוראות" in normalized
        )

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        if tag in {"script", "style"}:
            self._ignore_depth += 1
            return
        if self._ignore_depth:
            return

        self._tag_depth += 1

        attrs_dict = {key: value for key, value in attrs}
        class_attr = (attrs_dict.get("class") or "").lower()

        if self._content_depth:
            self._content_depth += 1
        elif "theme-post-content" in class_attr:
            self._content_depth = 1

        if tag == "h1" and not self.title_parts:
            self._in_title = True

        if not self._content_depth and not self._in_title:
            return

        if tag in {"h2", "h3", "h4"}:
            self._heading_tag = tag
            self._heading_buffer = []

        if self._ingredient_depth:
            self._ingredient_depth += 1
        elif "ingredient" in class_attr:
            self._ingredient_depth = 1

        if self._step_depth:
            self._step_depth += 1
        elif "instruction" in class_attr or "direction" in class_attr or "step" in class_attr:
            self._step_depth = 1

        if self._ingredient_depth and tag in {"li", "p"}:
            self._in_ingredient_item = True
            self._ingredient_buffer = []

        if self._step_depth and tag in {"li", "p"}:
            self._in_step_item = True
            self._step_buffer = []

        if self._section == "ingredients" and tag in {"li", "p"} and not self._ingredient_depth:
            self._in_ingredient_item = True
            self._ingredient_buffer = []

        if self._section == "steps" and tag in {"li", "p"} and not self._step_depth:
            self._in_step_item = True
            self._step_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignore_depth:
            self._ignore_depth -= 1
            return
        if self._ignore_depth:
            return

        if not self._content_depth and not self._in_title:
            return

        if self._heading_tag == tag:
            heading_text = " ".join(self._heading_buffer).strip()
            if heading_text:
                if self._is_ingredient_heading(heading_text):
                    self._section = "ingredients"
                    self._section_depth = max(self._tag_depth - 1, 0)
                elif self._is_step_heading(heading_text):
                    self._section = "steps"
                    self._section_depth = max(self._tag_depth - 1, 0)
            self._heading_tag = None
            self._heading_buffer = []

        if tag == "h1" and self._in_title:
            self._in_title = False

        if self._in_ingredient_item and tag in {"li", "p"}:
            item = "".join(self._ingredient_buffer).strip()
            if item:
                self.ingredients.append(item)
            self._in_ingredient_item = False
            self._ingredient_buffer = []

        if self._in_step_item and tag in {"li", "p"}:
            item = "".join(self._step_buffer).strip()
            if item:
                self.steps.append(item)
            self._in_step_item = False
            self._step_buffer = []

        if self._ingredient_depth:
            self._ingredient_depth -= 1

        if self._step_depth:
            self._step_depth -= 1

        if self._tag_depth:
            self._tag_depth -= 1

        if self._content_depth:
            self._content_depth -= 1

        if self._section_depth is not None and self._tag_depth < self._section_depth:
            self._section = None
            self._section_depth = None

    def handle_data(self, data: str) -> None:
        if self._ignore_depth:
            return
        if not self._content_depth and not self._in_title:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        if self._heading_tag:
            self._heading_buffer.append(text)
        if self._in_ingredient_item:
            self._ingredient_buffer.append(text)
        if self._in_step_item:
            self._step_buffer.append(text)


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


def extract_recipe_data(recipe_html: str, url: str = "") -> RecipeData:
    parser = RecipeParser()
    parser.feed(recipe_html)
    name = " ".join(parser.title_parts).strip()
    return RecipeData(
        url=url,
        name=name,
        ingredients=parser.ingredients,
        steps=parser.steps,
    )


def fetch_recipe_data(url: str) -> RecipeData:
    recipe_html = fetch_html(url)
    return extract_recipe_data(recipe_html, url=url)


def format_list(items: Iterable[str]) -> str:
    return " | ".join(item.strip() for item in items if item.strip())


def write_csv(recipes: Iterable[RecipeData], output_path: str) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["url", "recipe_name", "ingredients", "steps"])
        for recipe in recipes:
            writer.writerow(
                [
                    unquote(recipe.url),
                    recipe.name,
                    format_list(recipe.ingredients),
                    format_list(recipe.steps),
                ]
            )


def main() -> int:
    print("Step 1: Fetch listing page and discover structure...")
    print(f"Fetching {RECIPES_URL}")
    recipe_links = collect_recipe_links(RECIPES_URL)
    print(f"Found {len(recipe_links)} recipe link(s).")

    print("Step 2: Fetch recipe pages and extract details...")
    recipes = [fetch_recipe_data(url) for url in sorted(recipe_links)]
    print(f"Extracted {len(recipes)} recipe record(s).")

    output_path = "recipes.csv"
    write_csv(recipes, output_path)
    print(f"Wrote {len(recipes)} recipe rows to {output_path}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
