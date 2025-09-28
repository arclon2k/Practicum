import json
from pathlib import Path

from hm_tr_to_shopify.parser import merge_colorway_products, parse_product_json
from hm_tr_to_shopify.shopify_csv import HEADERS, to_shopify_rows


SAMPLE_PATH = Path(__file__).parent.parent / "samples" / "sample_product.json"


def load_sample_product():
    data = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    return parse_product_json(data, status="active")


def test_to_shopify_rows_structure():
    product = load_sample_product()
    rows = to_shopify_rows(product)
    assert rows, "Expected at least one row"
    first_row = rows[0]
    assert set(first_row.keys()) == set(HEADERS)
    assert first_row["Handle"] == "123456"
    assert first_row["Title"] == "Pilili Elbise"
    assert first_row["Variant SKU"] == "123456001"
    assert first_row["Variant Price"] == "399.99"
    qty_values = [row["Variant Inventory Qty"] for row in rows if row["Variant SKU"]]
    assert qty_values[:3] == ["1", "0", "1"]


def test_merge_colorway_products_combines_variants():
    data = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    black = data.copy()
    black["articles"] = data["articles"][:2]
    red = data.copy()
    red["articles"] = data["articles"][2:]

    product_black = parse_product_json(black, status="active")
    product_red = parse_product_json(red, status="active")
    merged = merge_colorway_products([product_black, product_red])
    assert len(merged) == 1
    merged_product = merged[0]
    assert len(merged_product.variants) == 3
    colors = {variant.color for variant in merged_product.variants}
    assert colors == {"Siyah", "Kırmızı"}
