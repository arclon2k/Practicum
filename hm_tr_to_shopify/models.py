"""Data models for H&M Turkey scraper."""
from __future__ import annotations

from dataclasses import field
from typing import Optional

try:  # pragma: no cover - optional dependency fallback
    from pydantic.dataclasses import dataclass
except ImportError:  # pragma: no cover
    from dataclasses import dataclass


@dataclass
class Image:
    """Represents a product image."""

    url: str
    position: int
    alt_text: Optional[str] = None
    variant_color: Optional[str] = None


@dataclass
class Variant:
    """Represents a product variant (color/size combination)."""

    sku: str
    color: str
    size: Optional[str]
    price: float
    compare_at_price: Optional[float]
    available: bool
    barcode: Optional[str] = None
    weight: Optional[float] = None
    images: list[Image] = field(default_factory=list)


@dataclass
class Product:
    """Represents a normalized product with variants and metadata."""

    handle: str
    title: str
    body_html: str
    vendor: str
    product_type: str
    tags: list[str]
    status: str
    options: list[str]
    variants: list[Variant]
    images: list[Image]
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    source_url: Optional[str] = None
