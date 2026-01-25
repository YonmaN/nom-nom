#!/usr/bin/env python3
"""Recipe scraper for https://ketochef.co.il/recipes/.

Steps implemented:
1) Fetch the listing page and discover recipe links.
2) Extract recipe names from the main listing page.
3) Traverse all listing pages to collect all recipe names.
4) Visit each recipe page and pull the title, ingredients, and instructions.
5) Store the results in a local CSV.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable, List, Optional, Set
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

BASE_URL = "https://ketochef.co.il/"
RECIPES_URL = "https://ketochef.co.il/recipes/"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_1) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/116.0.0.0 Safari/537.36"
)

INGREDIENT_KEYWORDS = {"מצרכים", "רכיבים", "מרכיבים", "ingredients"}
INSTRUCTION_KEYWORDS = {
    "אופן הכנה",
    "אופן ההכנה",
    "הוראות",
    "הכנה",
    "שיטת הכנה",
    "instructions",
    "directions",
    "method",
}


@dataclass
class Recipe:
    url: str
    name: str
    ingredients: List[str]
    instructions: List[str]


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


class ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._current_href: Optional[str] = None
        self._buffer: List[str] = []
        self.recipe_names: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        if tag != "a":
            return
        href = None
        for key, value in attrs:
            if key == "href" and value:
                href = value
                break
        if href:
            self._current_href = href
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._current_href:
            return
        text = " ".join(" ".join(self._buffer).split())
        if text:
            absolute = urljoin(BASE_URL, self._current_href)
            if is_recipe_link(absolute):
                self.recipe_names.append(text)
        self._current_href = None
        self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._buffer.append(data)


class RecipeContentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title: Optional[str] = None
        self._in_h1 = False
        self._heading_buffer: List[str] = []
        self._capture_heading = False
        self._section: Optional[str] = None
        self._section_stack: List[str] = []
        self.ingredients_raw: List[str] = []
        self.instructions_raw: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        attrs_dict = {key: (value or "") for key, value in attrs}
        class_attr = attrs_dict.get("class", "")
        class_tokens = {token.strip().lower() for token in class_attr.split() if token.strip()}

        if tag == "h1":
            self._in_h1 = True

        if tag in {"h2", "h3", "h4"}:
            self._heading_buffer = []
            self._capture_heading = True

        if class_tokens & {"ingredients", "ingredient", "recipe-ingredients"}:
            self._section_stack.append("ingredients")
        elif class_tokens & {"instructions", "instruction", "directions", "method"}:
            self._section_stack.append("instructions")
        else:
            self._section_stack.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1":
            self._in_h1 = False
        if tag in {"h2", "h3", "h4"} and self._capture_heading:
            heading_text = " ".join(" ".join(self._heading_buffer).split())
            self._section = classify_heading(heading_text)
            self._capture_heading = False
            self._heading_buffer = []
        if self._section_stack:
            self._section_stack.pop()

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return

        if self._in_h1 and not self.title:
            self.title = text

        if self._capture_heading:
            self._heading_buffer.append(text)
            return

        active_section = self._section
        if self._section_stack and self._section_stack[-1]:
            active_section = self._section_stack[-1]

        if active_section == "ingredients":
            self.ingredients_raw.append(text)
        elif active_section == "instructions":
            self.instructions_raw.append(text)


def fetch_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def is_recipe_link(link: str) -> bool:
    parsed = urlparse(link)
    if parsed.netloc and parsed.netloc != urlparse(BASE_URL).netloc:
        return False
    path = parsed.path.rstrip("/")
    if path in {"/recipes", "/recipes/page"}:
        return False
    if path.startswith("/recipes/page/"):
        return False
    return path.startswith("/recipes/")


def is_listing_page(link: str) -> bool:
    parsed = urlparse(link)
    if parsed.netloc and parsed.netloc != urlparse(BASE_URL).netloc:
        return False
    path = parsed.path.rstrip("/")
    if path == "/recipes":
        return True
    if path.startswith("/recipes/page/"):
        return True
    return "page=" in parsed.query and path.startswith("/recipes")


def normalize_links(links: Iterable[str]) -> Set[str]:
    normalized = set()
    for link in links:
        absolute = urljoin(BASE_URL, link)
        if is_recipe_link(absolute):
            normalized.add(absolute)
    return normalized


def extract_recipe_links(listing_html: str) -> Set[str]:
    parser = LinkParser()
    parser.feed(listing_html)
    return normalize_links(parser.links)


def extract_recipe_names_from_listing(listing_html: str) -> List[str]:
    parser = ListingParser()
    parser.feed(listing_html)
    return parser.recipe_names


def extract_listing_pages(listing_html: str) -> Set[str]:
    parser = LinkParser()
    parser.feed(listing_html)
    listing_pages = set()
    for link in parser.links:
        absolute = urljoin(BASE_URL, link)
        if is_listing_page(absolute):
            listing_pages.add(absolute)
    return listing_pages


def collect_listing_pages(start_url: str) -> List[str]:
    seen = set()
    to_visit = [start_url]
    while to_visit:
        url = to_visit.pop()
        if url in seen:
            continue
        seen.add(url)
        try:
            html_text = fetch_html(url)
        except Exception as exc:  # pylint: disable=broad-except
            print(f"Failed to fetch listing page {url}: {exc}", file=sys.stderr)
            continue
        for link in extract_listing_pages(html_text):
            if link not in seen:
                to_visit.append(link)
    return sorted(seen)


def classify_heading(text: str) -> Optional[str]:
    normalized = normalize_heading(text)
    for keyword in INGREDIENT_KEYWORDS:
        if keyword in normalized:
            return "ingredients"
    for keyword in INSTRUCTION_KEYWORDS:
        if keyword in normalized:
            return "instructions"
    return None


def normalize_heading(text: str) -> str:
    cleaned = re.sub(r"[:\s]+", " ", text).strip().lower()
    return cleaned


def extract_json_ld_recipe(html_text: str) -> Optional[Recipe]:
    script_blocks = re.findall(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html_text,
        re.DOTALL | re.IGNORECASE,
    )
    for block in script_blocks:
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        recipe_obj = find_recipe_object(data)
        if recipe_obj:
            name = recipe_obj.get("name")
            ingredients = coerce_list(recipe_obj.get("recipeIngredient"))
            instructions = normalize_instructions(recipe_obj.get("recipeInstructions"))
            if name:
                return Recipe("", str(name), ingredients, instructions)
    return None


def find_recipe_object(data: object) -> Optional[dict]:
    if isinstance(data, dict):
        if is_recipe_type(data):
            return data
        graph = data.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                if isinstance(item, dict) and is_recipe_type(item):
                    return item
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and is_recipe_type(item):
                return item
    return None


def is_recipe_type(item: dict) -> bool:
    recipe_type = item.get("@type")
    if isinstance(recipe_type, list):
        return any(str(entry).lower() == "recipe" for entry in recipe_type)
    if isinstance(recipe_type, str):
        return recipe_type.lower() == "recipe"
    return False


def coerce_list(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [cleanup_text(value)]
    if isinstance(value, list):
        result: List[str] = []
        for entry in value:
            if isinstance(entry, str):
                result.append(cleanup_text(entry))
            elif isinstance(entry, dict):
                text = entry.get("text")
                if isinstance(text, str):
                    result.append(cleanup_text(text))
        return [item for item in result if item]
    return []


def normalize_instructions(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [cleanup_text(value)]
    if isinstance(value, list):
        steps: List[str] = []
        for entry in value:
            if isinstance(entry, str):
                steps.append(cleanup_text(entry))
            elif isinstance(entry, dict):
                if "text" in entry and isinstance(entry["text"], str):
                    steps.append(cleanup_text(entry["text"]))
                elif "itemListElement" in entry:
                    steps.extend(normalize_instructions(entry["itemListElement"]))
        return [step for step in steps if step]
    if isinstance(value, dict):
        if "text" in value and isinstance(value["text"], str):
            return [cleanup_text(value["text"])]
        if "itemListElement" in value:
            return normalize_instructions(value["itemListElement"])
    return []


def cleanup_text(text: str) -> str:
    unescaped = html.unescape(text)
    cleaned = re.sub(r"\s+", " ", unescaped).strip()
    return cleaned


def parse_recipe_html(html_text: str) -> Recipe:
    json_ld_recipe = extract_json_ld_recipe(html_text)
    parser = RecipeContentParser()
    parser.feed(html_text)

    name = parser.title or (json_ld_recipe.name if json_ld_recipe else "")
    ingredients = merge_section_data(
        parser.ingredients_raw,
        json_ld_recipe.ingredients if json_ld_recipe else [],
    )
    instructions = merge_section_data(
        parser.instructions_raw,
        json_ld_recipe.instructions if json_ld_recipe else [],
    )
    return Recipe("", name, ingredients, instructions)


def merge_section_data(raw: List[str], json_ld: List[str]) -> List[str]:
    merged: List[str] = []
    for entry in raw + json_ld:
        cleaned = cleanup_text(entry)
        if not cleaned:
            continue
        if is_heading_text(cleaned):
            continue
        if cleaned not in merged:
            merged.append(cleaned)
    return merged


def is_heading_text(text: str) -> bool:
    normalized = normalize_heading(text)
    for keyword in INGREDIENT_KEYWORDS | INSTRUCTION_KEYWORDS:
        if keyword in normalized:
            return True
    return False


def collect_recipe_links(listing_pages: Iterable[str]) -> List[str]:
    links: Set[str] = set()
    for page in listing_pages:
        try:
            html_text = fetch_html(page)
        except Exception as exc:  # pylint: disable=broad-except
            print(f"Failed to fetch listing page {page}: {exc}", file=sys.stderr)
            continue
        links.update(extract_recipe_links(html_text))
    return sorted(links)


def fetch_recipe(url: str) -> Recipe:
    html_text = fetch_html(url)
    recipe = parse_recipe_html(html_text)
    recipe.url = url
    if not recipe.name:
        recipe.name = url.rstrip("/").split("/")[-1].replace("-", " ")
    return recipe


def write_csv(recipes: Iterable[Recipe], output_path: str) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["url", "name", "ingredients", "instructions"],
        )
        writer.writeheader()
        for recipe in recipes:
            writer.writerow(
                {
                    "url": recipe.url,
                    "name": recipe.name,
                    "ingredients": "\n".join(recipe.ingredients),
                    "instructions": "\n".join(recipe.instructions),
                }
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape ketochef.co.il recipes into a CSV."
    )
    parser.add_argument(
        "--names-only",
        action="store_true",
        help="Print recipe names from the main listing page only (step 2).",
    )
    parser.add_argument(
        "--list-names",
        action="store_true",
        help="Print recipe names from all listing pages (step 3).",
    )
    parser.add_argument(
        "--output",
        default="ketochef-recipes.csv",
        help="CSV output path.",
    )
    args = parser.parse_args()

    if args.names_only:
        listing_html = fetch_html(RECIPES_URL)
        for name in extract_recipe_names_from_listing(listing_html):
            print(name)
        return

    listing_pages = collect_listing_pages(RECIPES_URL)
    if args.list_names:
        names: List[str] = []
        for page in listing_pages:
            try:
                listing_html = fetch_html(page)
            except Exception as exc:  # pylint: disable=broad-except
                print(f"Failed to fetch listing page {page}: {exc}", file=sys.stderr)
                continue
            names.extend(extract_recipe_names_from_listing(listing_html))
        for name in sorted(dict.fromkeys(names)):
            print(name)
        return

    recipe_links = collect_recipe_links(listing_pages)
    recipes = [fetch_recipe(url) for url in recipe_links]
    write_csv(recipes, args.output)
    print(f"Saved {len(recipes)} recipes to {args.output}")


if __name__ == "__main__":
    main()
