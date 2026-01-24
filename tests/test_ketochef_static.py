import importlib.util
import sys
from pathlib import Path


FIXTURE_PATH = Path(__file__).parents[1] / "kitochef.html"


def load_scraper_module():
    scraper_path = Path(__file__).parents[1] / "ketochef-recipe-scraper.py"
    spec = importlib.util.spec_from_file_location("ketochef_scraper", scraper_path)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError("Could not load scraper module")
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_ketochef_fixture_parsing() -> None:
    scraper = load_scraper_module()
    html = FIXTURE_PATH.read_text(encoding="utf-8")

    recipe = scraper.extract_recipe_details(html, "https://ketochef.co.il/recipe/example")

    assert recipe.name == "המבורגר ברוקולי וגבינות צמחוני"
    assert recipe.ingredients == [
        "2 כוסות ברוקולי קצוץ",
        "1 כוס גבינת צ'דר מגוררת",
        "1 ביצה",
    ]
    assert recipe.instructions == [
        "לערבב את כל המרכיבים בקערה.",
        "ליצור קציצות ולצלות במחבת משומנת.",
        "להגיש חם.",
    ]
