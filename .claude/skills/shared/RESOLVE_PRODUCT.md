# Shared — Resolve Product

Resolve a WooCommerce Marketplace product to its numeric ID. Used by every
detect-* skill and the orchestrator.

Accept either a **numeric product ID** or a **product URL** (e.g.
`https://woocommerce.com/products/product-bundles/`).

- If given a numeric ID: use it directly.
- If given a URL: extract the slug from the URL path (e.g. `product-bundles`
  from `.../products/product-bundles/`), then try the following lookups **in
  order**, stopping at the first one that returns an ID:
  1. **MCP lookup** — call `woocommerce-products-list` with `slug: <slug>`.
     Use the returned ID if successful.
  2. **DOM scrape fallback** (use when step 1 fails for any reason — 403,
     network error, empty result, etc.) — fetch the URL with `Bash`
     (`curl -fsSL <url>`) and search the HTML for a
     `data-tracks-product-id="<digits>"` attribute inside the
     `wccom-product-add-to-cart-button` div. Regex:
     `data-tracks-product-id="([0-9]+)"`. Use the captured digits as the ID.
  3. **Ask the user** — if both lookups fail, ask: "I wasn't able to look up
     the product ID automatically. Could you share the numeric product ID?"
     and wait for the reply.
- If neither a URL nor an ID is provided: ask for one before proceeding.

After resolving, call `woocommerce-products-get` with the resolved ID to
retrieve the product name. Store it as `[product_name]`. Also store the
original slug if you have it — some downstream steps (knowledge base) use it.
