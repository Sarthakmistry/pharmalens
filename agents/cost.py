"""
agents/cost.py
Token usage accumulator and cost estimator for a pipeline batch run.

Gemini 2.5 Flash pricing used here:
  Input (non-cached): $0.15 / 1M tokens
  Input (cached):     $0.0375 / 1M tokens  (75% discount via context caching)
  Output:             $0.60 / 1M tokens

Usage:
  from agents.cost import ledger
  ledger.record(response.usage_metadata)   # called after each LLM call
  ledger.report()                          # called at end of batch
  ledger.reset()                           # called before next batch
"""

from dataclasses import dataclass, field
from agents.logger import get_logger

logger = get_logger("pharmalens.cost")

PRICE_INPUT_PER_M  = 0.15
PRICE_CACHED_PER_M = 0.0375
PRICE_OUTPUT_PER_M = 0.60


@dataclass
class TokenLedger:
    input_tokens:  int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    calls:         int = 0

    def record(self, usage) -> None:
        """Accumulate token counts from a GenerateContentResponse.usage_metadata object."""
        if usage is None:
            return
        self.input_tokens  += getattr(usage, "prompt_token_count", 0) or 0
        self.cached_tokens += getattr(usage, "cached_content_token_count", 0) or 0
        self.output_tokens += getattr(usage, "candidates_token_count", 0) or 0
        self.calls += 1

    @property
    def uncached_tokens(self) -> int:
        return self.input_tokens - self.cached_tokens

    @property
    def estimated_cost_usd(self) -> float:
        return (
            self.uncached_tokens / 1_000_000 * PRICE_INPUT_PER_M
            + self.cached_tokens  / 1_000_000 * PRICE_CACHED_PER_M
            + self.output_tokens  / 1_000_000 * PRICE_OUTPUT_PER_M
        )

    def report(self) -> None:
        logger.info("COST | ── batch token usage ──────────────────────────────")
        logger.info(f"COST | LLM calls:      {self.calls:,}")
        logger.info(f"COST | Input tokens:   {self.input_tokens:,}  ({self.cached_tokens:,} served from cache)")
        logger.info(f"COST | Output tokens:  {self.output_tokens:,}")
        logger.info(f"COST | Est. cost:      ${self.estimated_cost_usd:.4f} USD")
        logger.info("COST | ────────────────────────────────────────────────────")

    def reset(self) -> None:
        self.input_tokens = self.cached_tokens = self.output_tokens = self.calls = 0


# module-level singleton — shared across compiler.py and orchestrator.py
ledger = TokenLedger()
