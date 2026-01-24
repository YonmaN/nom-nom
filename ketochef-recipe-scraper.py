#!/usr/bin/env python3
"""KetoChef recipe scraper for https://ketochef.co.il/recipes/.

Steps implemented:
1) Fetch KetoChef listing page and retrieve recipe names from main page.
2) Traverse listing pagination to collect all recipe names + links.
3) Visit each recipe page and pull its title.
4) Enrich with ingredients + instructions, write to CSV.
"""

from __future__ import annotations

import csv
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
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
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
            absolute = urljoin(self.base_url, self._current_href)
            if is_recipe_link(absolute, self.base_url):
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
        self._section_stack: List[str] = []
        self.ingredients: List[str] = []
        self.instructions: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        attrs_dict = {key: (value or "") for key, value in attrs}
        class_attr = attrs_dict.get("class", "")
        class_tokens = {token.strip().lower() for token in class_attr.split() if token.strip()}

        if tag == "h1":
            self._in_h1 = True

        if class_tokens & {"ingredients", "ingredient", "recipe-ingredients"}:
            self._section_stack.append("ingredients")
        elif class_tokens & {"instructions", "instruction", "directions", "method"}:
            self._section_stack.append("instructions")
        else:
            self._section_stack.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1":
            self._in_h1 = False
        if self._section_stack:
            self._section_stack.pop()

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return

        if self._in_h1 and not self.title:
            self.title = text

        if self._section_stack:
            section = self._section_stack[-1]
            if section == "ingredients":
                self.ingredients.append(text)
            elif section == "instructions":
                self.instructions.append(text)


def fetch_html(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="ignore")


def is_recipe_link(link: str, base_url: str) -> bool:
    parsed = urlparse(link)
    base = urlparse(base_url)
    if parsed.netloc and parsed.netloc != base.netloc:
        return False
    path = parsed.path.rstrip("/")
    if path in {"/recipes", ""}:
        return False
    if path.startswith("/recipe_type"):
        return False
    return "/recipe" in path or "/recipes/" in path


def is_listing_page(link: str, base_url: str) -> bool:
    parsed = urlparse(link)
    base = urlparse(base_url)
    if parsed.netloc and parsed.netloc != base.netloc:
        return False
    path = parsed.path.rstrip("/")
    if path == "/recipes":
        return True
    return path.startswith("/recipes") and ("/page/" in path or "page=" in parsed.query)


def normalize_links(links: Iterable[str], base_url: str) -> Set[str]:
    normalized = set()
    for link in links:
        absolute = urljoin(base_url, link)
        if is_recipe_link(absolute, base_url):
            normalized.add(absolute)
    return normalized


def extract_recipe_links(listing_html: str, base_url: str) -> Set[str]:
    parser = LinkParser()
    parser.feed(listing_html)
    return normalize_links(parser.links, base_url)


def extract_recipe_names_from_listing(listing_html: str, base_url: str) -> List[str]:
    parser = ListingParser(base_url)
    parser.feed(listing_html)
    return parser.recipe_names


def extract_listing_pages(listing_html: str, base_url: str) -> Set[str]:
    parser = LinkParser()
    parser.feed(listing_html)
    listing_pages = set()
    for link in parser.links:
        absolute = urljoin(base_url, link)
        if is_listing_page(absolute, base_url):
            listing_pages.add(absolute)
    return listing_pages


def extract_json_ld_recipe(html: str) -> Optional[Recipe]:
    script_blocks = re.findall(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    for block in script_blocks:
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue

        candidates = data if isinstance(data, list) else [data]
        for entry in candidates:
            if not isinstance(entry, dict):
                continue
            entry_type = entry.get("@type") or entry.get("type")
            if isinstance(entry_type, list):
                is_recipe = any(t.lower() == "recipe" for t in entry_type if isinstance(t, str))
            else:
                is_recipe = isinstance(entry_type, str) and entry_type.lower() == "recipe"
            if not is_recipe:
                continue

            name = str(entry.get("name") or "").strip()
            ingredients = [i.strip() for i in entry.get("recipeIngredient", []) if isinstance(i, str)]
            instructions_raw = entry.get("recipeInstructions", [])
            instructions: List[str] = []
            if isinstance(instructions_raw, list):
                for instruction in instructions_raw:
                    if isinstance(instruction, str):
                        instructions.append(instruction.strip())
                    elif isinstance(instruction, dict):
                        text = instruction.get("text")
                        if isinstance(text, str):
                            instructions.append(text.strip())
            elif isinstance(instructions_raw, str):
                instructions = [instructions_raw.strip()]

            return Recipe(
                url="",
                name=name,
                ingredients=ingredients,
                instructions=instructions,
            )

    return None


def extract_recipe_details(recipe_html: str, url: str) -> Recipe:
    json_ld_recipe = extract_json_ld_recipe(recipe_html)
    if json_ld_recipe and json_ld_recipe.name:
        json_ld_recipe.url = url
        return json_ld_recipe

    parser = RecipeContentParser()
    parser.feed(recipe_html)
    name = parser.title or ""
    ingredients = parser.ingredients
    instructions = parser.instructions
    return Recipe(url=url, name=name, ingredients=ingredients, instructions=instructions)


def write_csv(recipes: Iterable[Recipe], output_path: str) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["url", "name", "ingredients", "instructions"])
        for recipe in recipes:
            writer.writerow(
                [
                    recipe.url,
                    recipe.name,
                    " | ".join(recipe.ingredients),
                    " | ".join(recipe.instructions),
                ]
            )


def main() -> int:
    print("Step 1: Retrieve recipe names from the main KetoChef listing page...")
    listing_html = fetch_html(RECIPES_URL)
    names = extract_recipe_names_from_listing(listing_html, BASE_URL)
    if names:
        print(f"Found {len(names)} name(s):", names)
    else:
        print("No recipe names found on the listing page with current selectors.")

    print("Step 2: Collect all recipe links and names from listing pages...")
    listing_pages = extract_listing_pages(listing_html, BASE_URL) | {RECIPES_URL}
    recipe_links: Set[str] = set()
    all_names: List[str] = []
    for page_url in sorted(listing_pages):
        try:
            page_html = listing_html if page_url == RECIPES_URL else fetch_html(page_url)
        except Exception as exc:
            print(f"Failed to fetch listing page {page_url}: {exc}")
            continue
        recipe_links.update(extract_recipe_links(page_html, BASE_URL))
        all_names.extend(extract_recipe_names_from_listing(page_html, BASE_URL))

    if all_names:
        print(f"Collected {len(all_names)} recipe name(s) from listings.")
    print(f"Found {len(recipe_links)} recipe link(s).")

    print("Step 3 & 4: Retrieve each recipe and extract details...")
    recipes: List[Recipe] = []
    for link in sorted(recipe_links):
        try:
            html = fetch_html(link)
        except Exception as exc:
            print(f"Failed to fetch {link}: {exc}")
            continue
        recipe = extract_recipe_details(html, link)
        recipes.append(recipe)

    output_path = "recipes.csv"
    write_csv(recipes, output_path)
    print(f"Wrote {len(recipes)} recipes to {output_path}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
