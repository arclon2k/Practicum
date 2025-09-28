"""Asynchronous crawler for H&M Turkey."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import random
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import httpx
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from .models import Product
from .parser import merge_colorway_products, parse_product_json

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://www2.hm.com"
ROBOTS_URL = urljoin(BASE_URL, "/robots.txt")
RATE_LIMIT_SECONDS = 0.6
MAX_RETRIES = 3
BACKOFF_FACTOR = 1.5


class RobotsCache:
    """Caches robots.txt directives to ensure compliance."""

    def __init__(self) -> None:
        self._fetched = False
        self._disallow: list[str] = []

    async def ensure(self) -> None:
        if self._fetched:
            return
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(ROBOTS_URL)
                resp.raise_for_status()
            except httpx.HTTPError as exc:  # noqa: PERF203
                LOGGER.warning("Failed to fetch robots.txt", extra={"error": str(exc)})
                self._fetched = True
                return
            self._disallow = [line.split(":", 1)[1].strip() for line in resp.text.splitlines() if line.startswith("Disallow:")]
            self._fetched = True

    async def is_allowed(self, url: str) -> bool:
        await self.ensure()
        path = urlparse(url).path
        for rule in self._disallow:
            if rule == "/":
                return False
            if path.startswith(rule):
                return False
        return True


class HMTRCrawler:
    """Crawls H&M Turkey categories and product pages using Playwright."""

    def __init__(
        self,
        *,
        concurrency: int = 4,
        max_products: int | None = None,
        debug_network: bool = False,
        proxy: str | None = None,
    ) -> None:
        self.concurrency = concurrency
        self.max_products = max_products
        self.debug_network = debug_network
        self.proxy = proxy
        self._robots = RobotsCache()
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._playwright = None
        self._semaphore = asyncio.Semaphore(concurrency)
        self._collected_products: list[Product] = []
        self._seen_urls: set[str] = set()
        self._rate_lock = asyncio.Lock()
        self._last_request = 0.0
        self._debug_dir: Path | None = Path("debug_network") if debug_network else None
        if self._debug_dir:
            self._debug_dir.mkdir(exist_ok=True)
        self._product_tasks: set[asyncio.Task] = set()

    async def __aenter__(self) -> "HMTRCrawler":
        self._playwright = await async_playwright().start()
        launch_kwargs = {"headless": True}
        if self.proxy:
            launch_kwargs["proxy"] = {"server": self.proxy}
        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self._context = await self._browser.new_context()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _throttle(self) -> None:
        async with self._rate_lock:
            elapsed = time.monotonic() - self._last_request
            wait_for = RATE_LIMIT_SECONDS + random.uniform(0.2, 0.6) - elapsed
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self._last_request = time.monotonic()

    async def gather(self, category_urls: Iterable[str], product_urls: Iterable[str]) -> list[Product]:
        """Crawl categories and product pages and return merged products."""

        await self._robots.ensure()
        tasks = []
        for category_url in category_urls:
            tasks.append(asyncio.create_task(self._collect_from_category(category_url)))
        if tasks:
            await asyncio.gather(*tasks)

        for product_url in product_urls:
            await self._enqueue_product(product_url)

        if self._product_tasks:
            await asyncio.gather(*self._product_tasks)
        merged = merge_colorway_products(self._collected_products)
        LOGGER.info(
            "Crawling complete",
            extra={
                "products": len(merged),
                "variants": sum(len(p.variants) for p in merged),
                "skipped": len(self._seen_urls) - len(self._collected_products),
            },
        )
        return merged

    async def _collect_from_category(self, category_url: str) -> None:
        if not await self._robots.is_allowed(category_url):
            LOGGER.warning("Category blocked by robots.txt", extra={"url": category_url})
            return
        page = await self._get_page()
        try:
            await self._throttle()
            LOGGER.info("Loading category", extra={"url": category_url})
            await page.goto(category_url, wait_until="networkidle")
            product_links = await self._extract_product_links(page)
            LOGGER.info("Discovered products", extra={"url": category_url, "count": len(product_links)})
            limited_links = product_links[: self.max_products] if self.max_products else product_links
            for link in limited_links:
                await self._enqueue_product(link)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Failed to process category", extra={"url": category_url, "error": str(exc)})
        finally:
            await page.close()

    async def _enqueue_product(self, product_url: str) -> None:
        if not await self._robots.is_allowed(product_url):
            LOGGER.debug("Product blocked by robots.txt", extra={"url": product_url})
            return
        if product_url in self._seen_urls:
            return
        self._seen_urls.add(product_url)
        task = asyncio.create_task(self._with_semaphore(self._process_product(product_url)))
        self._product_tasks.add(task)
        task.add_done_callback(self._product_tasks.discard)

    async def _with_semaphore(self, coro):
        async with self._semaphore:
            await coro

    async def _get_page(self) -> Page:
        assert self._context is not None
        page = await self._context.new_page()
        if self.debug_network:
            page.on("response", lambda response: asyncio.create_task(self._handle_debug_response(response)))
        return page

    async def _handle_debug_response(self, response) -> None:  # noqa: ANN001
        if not self.debug_network or not self._debug_dir:
            return
        try:
            content_type = response.headers.get("content-type", "")
            if "application/json" not in content_type:
                return
            url = response.url
            if not any(keyword in url for keyword in ["product", "articles", "variants"]):
                return
            body = await response.text()
            digest = hashlib.sha1(url.encode()).hexdigest()  # noqa: S324
            path = self._debug_dir / f"{digest}.json"
            path.write_text(body, encoding="utf-8")
        except Exception:  # noqa: BLE001
            LOGGER.debug("Failed to write debug response", exc_info=True)

    async def _extract_product_links(self, page: Page) -> list[str]:
        anchors = await page.eval_on_selector_all(
            "a[href*='/productpage.']",
            "elements => elements.map(el => el.href)",
        )
        links: list[str] = []
        for href in anchors:
            if href and href.startswith("http"):
                links.append(href)
            else:
                links.append(urljoin(BASE_URL, href))
        return list(dict.fromkeys(links))

    async def _process_product(self, product_url: str) -> None:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                await self._throttle()
                page = await self._get_page()
                LOGGER.info("Loading product", extra={"url": product_url, "attempt": attempt})
                await page.goto(product_url, wait_until="domcontentloaded")
                product_json = await self._extract_product_json(page)
                if not product_json:
                    raise ValueError("Unable to locate product JSON")
                product_json["url"] = product_url
                product = parse_product_json(product_json, status="active")
                product.source_url = product_url
                self._collected_products.append(product)
                await page.close()
                return
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning(
                    "Failed to load product",
                    extra={"url": product_url, "attempt": attempt, "error": str(exc)},
                )
                if attempt == MAX_RETRIES:
                    return
                await asyncio.sleep(BACKOFF_FACTOR**attempt)
            finally:
                try:
                    await page.close()
                except Exception:  # noqa: BLE001
                    pass

    async def _extract_product_json(self, page: Page) -> dict | None:
        # Attempt to read known global variables
        candidates = [
            "() => window.__PRELOADED_STATE__",
            "() => window.__NUXT__",
            "() => window.__NEXT_DATA__",
            "() => window.hm && window.hm.product && window.hm.product.data",
        ]
        for script in candidates:
            try:
                data = await page.evaluate(script)
                if data:
                    product = self._normalize_state(data)
                    if product:
                        return product
            except Exception:  # noqa: BLE001
                continue
        # Fallback: parse script tags containing JSON
        content = await page.content()
        for snippet in self._extract_json_blobs(content):
            product = self._normalize_state(snippet)
            if product:
                return product
        return None

    def _normalize_state(self, data) -> dict | None:  # noqa: ANN001
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                return None
        if not isinstance(data, dict):
            return None
        possible_keys = [
            "product",
            "productData",
            "productDetail",
            "productItem",
        ]
        for key in possible_keys:
            if key in data and isinstance(data[key], dict):
                return data[key]
        # H&M specific nested state
        product_detail = data
        for key in ("product", "productPage", "articleData", "PDP"):  # heuristic path
            if isinstance(product_detail, dict) and key in product_detail:
                product_detail = product_detail[key]
        if isinstance(product_detail, dict) and "articles" in product_detail:
            return product_detail
        return None

    def _extract_json_blobs(self, html: str) -> Iterable[dict]:
        marker = "{\"product"  # basic heuristic
        if marker not in html:
            return []
        blobs: list[dict] = []
        for match in re.finditer(r"<script[^>]*>(.*?)</script>", html, re.DOTALL):
            script_body = match.group(1)
            if "product" not in script_body:
                continue
            script_body = script_body.strip()
            try:
                blob = json.loads(script_body)
                if isinstance(blob, dict):
                    blobs.append(blob)
            except json.JSONDecodeError:
                continue
        return blobs
