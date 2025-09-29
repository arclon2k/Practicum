"""Utilities for converting products to Shopify CSV rows."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .models import Image, Product, Variant

HEADERS = [
    "Handle",
    "Title",
    "Body (HTML)",
    "Vendor",
    "Type",
    "Tags",
    "Published",
    "Option1 Name",
    "Option1 Value",
    "Option2 Name",
    "Option2 Value",
    "Option3 Name",
    "Option3 Value",
    "Variant SKU",
    "Variant Price",
    "Variant Compare At Price",
    "Variant Inventory Tracker",
    "Variant Inventory Qty",
    "Variant Inventory Policy",
    "Variant Fulfillment Service",
    "Variant Requires Shipping",
    "Variant Taxable",
    "Variant Barcode",
    "Image Src",
    "Image Position",
    "Image Alt Text",
    "Variant Image",
    "Variant Weight Unit",
    "Status",
]


def _option_value(option_name: str, variant: Variant) -> str:
    if option_name.lower() == "color":
        return variant.color
    if option_name.lower() == "size":
        return variant.size or "One Size"
    if option_name.lower() == "title":
        return variant.sku
    return getattr(variant, option_name.lower(), "") or ""


def _format_price(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2f}"


def _inventory_qty(variant: Variant) -> str:
    return "1" if variant.available else "0"


def _image_tuple(image: Image) -> tuple[str, int, str]:
    return image.url, image.position, image.alt_text or ""


def to_shopify_rows(product: Product) -> list[dict[str, str]]:
    """Convert a normalized product into Shopify CSV rows."""

    rows: list[dict[str, str]] = []
    images_sorted = sorted(product.images, key=lambda img: img.position)
    used_images: set[str] = set()

    for variant_index, variant in enumerate(product.variants):
        row = {header: "" for header in HEADERS}
        row["Handle"] = product.handle
        if variant_index == 0:
            row["Title"] = product.title
            row["Body (HTML)"] = product.body_html
            row["Vendor"] = product.vendor
            row["Type"] = product.product_type
            row["Tags"] = ", ".join(product.tags)
        row["Published"] = "TRUE" if product.status == "active" else "FALSE"
        option_names = product.options[:3] + ["", "", ""]
        option_names = option_names[:3]
        for i, option_name in enumerate(option_names, start=1):
            if not option_name:
                continue
            row[f"Option{i} Name"] = option_name
            row[f"Option{i} Value"] = _option_value(option_name, variant)
        row["Variant SKU"] = variant.sku
        row["Variant Price"] = _format_price(variant.price)
        row["Variant Compare At Price"] = _format_price(variant.compare_at_price)
        row["Variant Inventory Tracker"] = ""
        row["Variant Inventory Qty"] = _inventory_qty(variant)
        row["Variant Inventory Policy"] = "deny"
        row["Variant Fulfillment Service"] = "manual"
        row["Variant Requires Shipping"] = "TRUE"
        row["Variant Taxable"] = "TRUE"
        row["Variant Barcode"] = variant.barcode or ""
        row["Variant Weight Unit"] = "kg"
        row["Status"] = product.status

        variant_image = _select_variant_image(variant, images_sorted)
        if variant_image:
            row["Image Src"], row["Image Position"], row["Image Alt Text"] = _image_tuple(variant_image)
            row["Variant Image"] = variant_image.url
            used_images.add(variant_image.url)
        rows.append(row)

    # Additional image rows for gallery images not tied to variants
    for image in images_sorted:
        if image.url in used_images:
            continue
        row = {header: "" for header in HEADERS}
        row["Handle"] = product.handle
        row["Image Src"], row["Image Position"], row["Image Alt Text"] = _image_tuple(image)
        rows.append(row)

    return rows


def _select_variant_image(variant: Variant, images_sorted: list[Image]) -> Image | None:
    if variant.images:
        return sorted(variant.images, key=lambda img: img.position)[0]
    for image in images_sorted:
        if image.variant_color and image.variant_color.lower() == variant.color.lower():
            return image
    return images_sorted[0] if images_sorted else None


def write_shopify_csv(products: Iterable[Product], output_path: Path) -> None:
    """Write Shopify CSV rows to a file."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=HEADERS)
        writer.writeheader()
        for product in products:
            for row in to_shopify_rows(product):
                writer.writerow(row)
