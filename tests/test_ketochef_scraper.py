import pathlib
import unittest
from importlib.machinery import SourceFileLoader


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRAPER_PATH = ROOT / "ketochef-recipe-scraper.py"
scraper = SourceFileLoader("ketochef_scraper", str(SCRAPER_PATH)).load_module()


class KetochefScraperFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page1 = (ROOT / "fixtures/ketochef_recipes_page1.html").read_text(
            encoding="utf-8"
        )
        self.page2 = (ROOT / "fixtures/ketochef_recipes_page2.html").read_text(
            encoding="utf-8"
        )
        self.recipe_page = (ROOT / "fixtures/ketochef_recipe_page.html").read_text(
            encoding="utf-8"
        )

    def test_extract_recipe_links_from_page1(self) -> None:
        links = scraper.extract_recipe_links(self.page1)
        self.assertEqual(
            links,
            {
                "https://ketochef.co.il/recipe/%D7%A1%D7%9C%D7%98-%D7%90%D7%91%D7%95%D7%A7%D7%93%D7%95",
                "https://ketochef.co.il/recipes/%D7%A7%D7%A6%D7%99%D7%A6%D7%95%D7%AA-%D7%98%D7%95%D7%A4%D7%95",
            },
        )

    def test_extract_recipe_links_from_page2(self) -> None:
        links = scraper.extract_recipe_links(self.page2)
        self.assertEqual(
            links,
            {
                "https://ketochef.co.il/recipe/%D7%9E%D7%A8%D7%A7-%D7%A2%D7%92%D7%91%D7%A0%D7%99%D7%95%D7%AA",
                "https://ketochef.co.il/recipes/%D7%A2%D7%95%D7%92%D7%AA-%D7%A9%D7%95%D7%A7%D7%95%D7%9C%D7%93",
            },
        )

    def test_extract_listing_pages(self) -> None:
        pages = scraper.extract_listing_pages(self.page1 + self.page2)
        self.assertEqual(
            pages,
            {
                "https://ketochef.co.il/recipes/page/2",
                "https://ketochef.co.il/recipes?page=3",
            },
        )

    def test_extract_recipe_data(self) -> None:
        data = scraper.extract_recipe_data(
            self.recipe_page, url="https://ketochef.co.il/recipe/avocado-salad"
        )
        self.assertEqual(data.name, "סלט אבוקדו עם עשבי תיבול")
        self.assertEqual(
            data.ingredients,
            ["2 אבוקדו בשלים", "1 כף שמן זית", "מלח ופלפל לפי הטעם"],
        )
        self.assertEqual(
            data.steps,
            [
                "חותכים את האבוקדו לקוביות.",
                "מערבבים עם שמן זית ותיבול.",
                "מגישים מיד.",
            ],
        )


if __name__ == "__main__":
    unittest.main()
