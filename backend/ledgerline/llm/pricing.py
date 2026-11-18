"""Token prices, used to ESTIMATE LLM cost from the token usage each provider reports for each call.

These are estimates, not billing: the provider's invoice can differ (taxes, credits, discounts, requests that failed
before usage was recorded, the exchange rate actually used). Reconcile against the provider's billing console.

Only prices verified against Anthropic's published list prices (checked 18 Nov 2026) are included. Any other model is
"unpriced": its calls are counted and reported as such, never silently priced at zero.
(The starter's table held prices per thousand tokens under a per-million label: every cost was 1,000x too low.)
"""
from __future__ import annotations

PRICES_CHECKED_ON = "2026-11-18"

# USD per million tokens: (input, output).
USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),  # prompts up to 100K tokens; Ledgerline's prompts are far below that
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimated cost of one call, or None when the model has no verified price."""
    if model not in USD_PER_MTOK:
        return None
    input_price, output_price = USD_PER_MTOK[model]
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000
