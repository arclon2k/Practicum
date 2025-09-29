"""Parsing helpers for converting H&M responses into internal models."""
from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict
from typing import Any, Iterable

from .models import Image, Product, Variant

LOGGER = logging.getLogger(__name__)


HANDLE_SANITIZE_RE = re.compile(r"[^a-z0-9-]+")
WHITESPACE_RE = re.compile(r"\s+")
SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\\1>", re.IGNORECASE | re.DOTALL)


def slugify(value: str) -> str:
    """Create a kebab-case slug suitable for Shopify handles."""

    value = value.strip().lower()
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.replace("&", " and ")
    value = WHITESPACE_RE.sub("-", value)
    value = HANDLE_SANITIZE_RE.sub("", value)
    value = value.strip("-")
    return value or "product"


def clean_html(html_text: str) -> str:
    """Sanitize HTML by removing script/style tags and trimming whitespace."""

    text = html_text or ""
    text = SCRIPT_STYLE_RE.sub("", text)
    return text.strip()


def extract_tags(product_json: dict[str, Any]) -> list[str]:
    """Collect tags from materials, colors, and categories."""

    tags: set[str] = set()
    materials = product_json.get("materials") or []
    if isinstance(materials, list):
        for material in materials:
            if isinstance(material, str):
                tags.add(material.strip())
    color = product_json.get("color") or product_json.get("colorName")
    if isinstance(color, str):
        tags.add(color.strip())
    breadcrumbs = product_json.get("breadcrumb") or product_json.get("breadcrumbs")
    if isinstance(breadcrumbs, Iterable):
        for crumb in breadcrumbs:
            if isinstance(crumb, str):
                tags.add(crumb.strip())
            elif isinstance(crumb, dict):
                label = crumb.get("label") or crumb.get("name")
                if label:
                    tags.add(str(label).strip())
    season = product_json.get("season")
    if isinstance(season, str):
        tags.add(season.strip())
    return sorted(tag for tag in tags if tag)


def merge_variant_images(variants: list[Variant], default_images: list[Image]) -> None:
    """Ensure variant-level images inherit product gallery if missing."""

    image_by_color = defaultdict(list)
    for image in default_images:
        if image.variant_color:
            image_by_color[image.variant_color.lower()].append(image)
    for variant in variants:
        if not variant.images:
            variant.images.extend(image_by_color.get(variant.color.lower(), []))


def parse_product_json(product_json: dict[str, Any], *, status: str) -> Product:
    """Parse a product JSON payload into a Product model."""

    title = product_json.get("title") or product_json.get("name") or ""
    if not title:
        raise ValueError("Product JSON missing title")
    handle_source = product_json.get("code") or product_json.get("productCode") or title
    handle = slugify(str(handle_source))
    description = product_json.get("description") or product_json.get("descriptionHtml")
    body_html = clean_html(description) if description else ""
    product_type = product_json.get("category") or product_json.get("mainCategory") or ""
    tags = extract_tags(product_json)

    options: list[str] = []
    option_map: dict[str, set[str]] = {}

    raw_variants = product_json.get("articles") or product_json.get("variants") or []
    if not isinstance(raw_variants, list):
        raise ValueError("Unexpected variant payload")

    variants: list[Variant] = []
    for raw in raw_variants:
        try:
            article_code = raw.get("code") or raw.get("articleCode") or raw.get("sku")
            if not article_code:
                LOGGER.debug("Skipping variant without article code", extra={"raw": raw})
                continue
            color_name = raw.get("color") or raw.get("colorName") or product_json.get("colorName")
            size_name = raw.get("size") or raw.get("sizeName") or raw.get("name")
            price = raw.get("price") or raw.get("priceValue") or product_json.get("price")
            if isinstance(price, dict):
                price = price.get("value") or price.get("current")
            compare_at = raw.get("compareAt") or raw.get("originalPrice")
            if isinstance(compare_at, dict):
                compare_at = compare_at.get("value") or compare_at.get("original")
            available = bool(raw.get("inStock", True))
            barcode = raw.get("ean") or raw.get("gtin")
            images: list[Image] = []
            gallery = raw.get("gallery") or raw.get("media") or []
            if isinstance(gallery, list):
                for idx, entry in enumerate(gallery, start=1):
                    url = entry.get("url") if isinstance(entry, dict) else entry
                    if not url:
                        continue
                    images.append(
                        Image(
                            url=url,
                            position=idx,
                            alt_text=f"{title} – {color_name}" if color_name else title,
                            variant_color=color_name,
                        )
                    )
            variant = Variant(
                sku=str(article_code),
                color=str(color_name or "Tek Renk"),
                size=str(size_name) if size_name else None,
                price=float(price) if price else 0.0,
                compare_at_price=float(compare_at) if compare_at else None,
                available=available,
                barcode=str(barcode) if barcode else None,
                images=images,
            )
            variants.append(variant)
            if variant.color:
                option_map.setdefault("Color", set()).add(variant.color)
            if variant.size:
                option_map.setdefault("Size", set()).add(variant.size)
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("Failed to parse variant", exc_info=exc)

    images: list[Image] = []
    gallery = product_json.get("gallery") or product_json.get("media") or []
    if isinstance(gallery, list):
        for idx, entry in enumerate(gallery, start=1):
            if isinstance(entry, dict):
                url = entry.get("url")
                color = entry.get("color") or entry.get("colorName")
            else:
                url = entry
                color = None
            if not url:
                continue
            images.append(
                Image(
                    url=url,
                    position=idx,
                    alt_text=f"{title} – {color}" if color else title,
                    variant_color=color,
                )
            )

    options = list(option_map.keys())
    if not options:
        options = ["Title"]
    merge_variant_images(variants, images)

    product = Product(
        handle=handle,
        title=title,
        body_html=body_html,
        vendor="H&M",
        product_type=str(product_type or ""),
        tags=tags,
        status=status,
        options=options,
        variants=variants,
        images=images,
        seo_title=product_json.get("seoTitle"),
        seo_description=product_json.get("seoDescription"),
        source_url=product_json.get("url") or product_json.get("productUrl"),
    )
    return product


def merge_colorway_products(products: Iterable[Product]) -> list[Product]:
    """Merge colorway entries that share the same handle into single products."""

    merged: dict[str, Product] = {}
    for product in products:
        existing = merged.get(product.handle)
        if not existing:
            merged[product.handle] = product
            continue
        existing.variants.extend(product.variants)
        existing.images.extend(product.images)
        existing.tags = sorted(set(existing.tags).union(product.tags))
    for product in merged.values():
        merge_variant_images(product.variants, product.images)
    return list(merged.values())
