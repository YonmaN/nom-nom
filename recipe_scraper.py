#!/usr/bin/env python3
"""Deprecated wrapper for the keto diet recipe scraper."""

from pathlib import Path
import runpy


def main() -> None:
    target = Path(__file__).with_name("keto-diet-recipe-scraper.py")
    runpy.run_path(target.as_posix(), run_name="__main__")


if __name__ == "__main__":
    main()
