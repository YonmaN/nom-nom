import pathlib
import unittest
from importlib.machinery import SourceFileLoader


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRAPER_PATH = ROOT / "omermiller-recipe-scraper.py"
scraper = SourceFileLoader("omermiller_scraper", str(SCRAPER_PATH)).load_module()


class OmerMillerScraperFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.listing_html = (ROOT / "fixtures/ketochef_listing_fixture.html").read_text(
            encoding="utf-8"
        )

    def test_extract_recipe_links(self) -> None:
        links = scraper.extract_recipe_links(
            self.listing_html,
            base_url="https://ketochef.co.il/",
            category_path="/recipes",
        )
        self.assertEqual(
            links,
            {
                "https://ketochef.co.il/recipe/סלט-אבוקדו",
                "https://ketochef.co.il/recipes/קציצות-טופו",
            },
        )

    def test_extract_listing_pages(self) -> None:
        pages = scraper.extract_listing_pages(
            self.listing_html,
            base_url="https://ketochef.co.il/",
            category_path="/recipes",
        )
        self.assertEqual(
            pages,
            {
                "https://ketochef.co.il/recipes/page/2/",
                "https://ketochef.co.il/recipes?paged=3",
            },
        )


if __name__ == "__main__":
    unittest.main()
