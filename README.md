# H&M Turkey to Shopify Exporter

`hm-tr-to-shopify` is a command-line tool that crawls product data from [H&M Turkey](https://www2.hm.com/tr_tr/) and exports it to a Shopify-compatible Product CSV. The scraper renders pages using Playwright, normalizes product variants and images, and outputs data ready for import.

## Features

- Asynchronous Playwright crawler with polite rate limiting and retry/backoff
- Robots.txt-aware category and product discovery
- Variant normalization (color/size) with product-level merging
- Shopify CSV mapping with configurable publication status
- Optional network capture for debugging product JSON payloads
- Sample product payload and unit tests for CSV mapping

## Installation

The project uses [Poetry](https://python-poetry.org/) for packaging. Install dependencies and Playwright browsers:

```bash
poetry install
poetry run playwright install chromium
```

## Usage

Invoke the CLI with one or more category or product URLs:

```bash
poetry run hm_tr_to_shopify \
  "https://www2.hm.com/tr_tr/kadin-alisveris/elbiseler.html" \
  --max-products 50 \
  --concurrency 4 \
  --out hm_tr_products.csv \
  --published true
```

### Options

- `--max-products N`: Limit number of items per category
- `--concurrency K`: Control the number of concurrent product workers (default 4)
- `--out PATH`: Destination CSV path (default `shopify.csv`)
- `--published true|false`: Published flag controlling Shopify `Status` and `Published`
- `--skip-images`: Avoid downloading image bytes (image URLs are still collected)
- `--proxy URL`: HTTP proxy passed to Playwright
- `--debug-network`: Save raw JSON responses in `./debug_network/`
- `--log-level LEVEL`: Standard Python logging level (default INFO)

The tool prints a summary once the export completes and writes the CSV using UTF-8 encoding.

## Testing

Run the unit test suite with pytest:

```bash
poetry run pytest
```

## Notes

- Respect H&M Turkey's Terms of Service and robots.txt directives.
- The scraper introduces random jitter between requests and retries on transient errors (HTTP 429/5xx).
- Shopify CSV headers conform to Shopify's required import format with inventory, pricing, and image data populated per variant.
