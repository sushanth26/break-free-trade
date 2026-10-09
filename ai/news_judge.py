"""News judge: one headline → relevance, direction, impact, action."""
from __future__ import annotations

from ai.client import AIClient, load_prompt
from ai.schemas import NewsJudgment


def judge_headline(ai: AIClient, headline: str, published_at, ticker: str, price: float,
                   zones: list[dict], regime: str) -> NewsJudgment | None:
    payload = {"headline": headline, "published_at": str(published_at), "ticker": ticker,
               "price": round(price, 2), "zones": zones, "regime": regime}
    return ai.ask("news_judge", load_prompt("news_judge"), payload, NewsJudgment)


def bias_from(j: NewsJudgment | None) -> str:
    """'bullish'/'bearish' when the judgment should steer trades, else ''."""
    if j is None or j.relevance == "none" or j.impact == "low" or j.direction == "neutral":
        return ""
    return j.direction
