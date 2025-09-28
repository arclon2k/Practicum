"""Command-line entrypoint for H&M Turkey to Shopify exporter."""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path
from typing import Iterable

from .crawler import HMTRCrawler
from .shopify_csv import write_shopify_csv

LOGGER = logging.getLogger(__name__)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export H&M Turkey products to Shopify CSV")
    parser.add_argument("urls", nargs="+", help="Category or product URLs")
    parser.add_argument("--max-products", type=int, default=None, help="Max products per category")
    parser.add_argument("--concurrency", type=int, default=4, help="Concurrent page workers")
    parser.add_argument("--out", type=Path, default=Path("shopify.csv"), help="Output CSV path")
    parser.add_argument("--published", type=str, default="true", choices=["true", "false"], help="Published flag")
    parser.add_argument("--skip-images", action="store_true", help="Skip downloading image bytes (URLs only)")
    parser.add_argument("--proxy", type=str, default=None, help="HTTP proxy for Playwright")
    parser.add_argument("--debug-network", action="store_true", help="Save raw network payloads")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser.parse_args(argv)


def split_urls(urls: Iterable[str]) -> tuple[list[str], list[str]]:
    categories: list[str] = []
    products: list[str] = []
    for url in urls:
        if "/productpage" in url:
            products.append(url)
        else:
            categories.append(url)
    return categories, products


async def run_async(args: argparse.Namespace) -> None:
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    categories, product_urls = split_urls(args.urls)
    published = args.published.lower() == "true"
    status = "active" if published else "draft"

    LOGGER.info(
        "Starting crawl",
        extra={
            "categories": len(categories),
            "products": len(product_urls),
            "max_products": args.max_products,
            "concurrency": args.concurrency,
        },
    )
    if args.skip_images:
        LOGGER.info("Image download skipped; only URLs will be captured")

    async with HMTRCrawler(
        concurrency=args.concurrency,
        max_products=args.max_products,
        debug_network=args.debug_network,
        proxy=args.proxy,
    ) as crawler:
        products = await crawler.gather(categories, product_urls)

    for product in products:
        product.status = status

    write_shopify_csv(products, args.out)

    total_variants = sum(len(product.variants) for product in products)
    print(f"Exported {len(products)} products ({total_variants} variants) -> {args.out}")


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    asyncio.run(run_async(args))


if __name__ == "__main__":
    main()
