"""Live cross-sectional scoring: wires Experiment B's frozen model into
real live Binance bars.

Experiment B's features are cross-sectional -- percentile ranks relative to
every other tracked coin at the same minute -- so a coin cannot be scored
in isolation. This engine tracks the whole live universe together, computes
features.compute_features() once per minute across all tracked pairs, and
scores every pair from that single shared computation.

Scores are the frozen linear_svm model's decision_function value: a
ranking score, NOT a calibrated probability (the guide is explicit that
multiplying a score by 100 does not make it a probability). The alert
threshold is PROVISIONAL -- computed from validation-era rows, not a real
ordinary-market-period background stream, so the live false-alert rate is
unvalidated per the build guide's K11 requirement. Every output says so.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import joblib
import pandas as pd

from pumpradar.engine import Bar
from pumpradar.exp_a import _get_scores
from pumpradar.features import MIN_BASELINE_OBS, compute_features

MARKET_API = "https://data-api.binance.vision/api/v3"
HISTORY_MINUTES = 1500  # ~23h baseline (features.BASELINE_MINUTES=1380) + embargo + current, with margin
BACKFILL_KLINE_LIMIT = 1000

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = PROJECT_ROOT / "models" / "model_B.joblib"
FEATURES_PATH = PROJECT_ROOT / "models" / "features_B.json"
THRESHOLD_PATH = PROJECT_ROOT / "models" / "threshold_B.json"


@dataclass(frozen=True)
class LiveScore:
    pair: str
    score: float | None
    scoring_status: str  # "scored" | "insufficient_history"
    as_of: str | None
    is_alert: bool


def load_frozen_bundle(
    model_path: Path = MODEL_PATH,
    features_path: Path = FEATURES_PATH,
    threshold_path: Path = THRESHOLD_PATH,
):
    """Load the frozen model + its feature list + its provisional threshold.
    Raises FileNotFoundError with a clear message if the bundle hasn't been
    generated yet, rather than scoring with nothing.
    """
    for path in (model_path, features_path, threshold_path):
        if not path.exists():
            raise FileNotFoundError(f"{path} not found -- run exp_b.freeze_deployment_model first")
    models_by_horizon = joblib.load(model_path)
    with open(features_path) as f:
        feature_info = json.load(f)
    with open(threshold_path) as f:
        threshold_info = json.load(f)

    horizon = feature_info["horizon_min"]
    return models_by_horizon[horizon], feature_info["feature_columns"], threshold_info


class CrossSectionalScoringEngine:
    """Tracks rolling bar history for the whole live universe, computes
    cross-sectional features once per minute, and scores every pair the
    frozen model has enough real history for.
    """

    def __init__(
        self,
        model,
        feature_columns: list[str],
        threshold: float,
        cooldown_minutes: float = 30,
        history_minutes: int = HISTORY_MINUTES,
    ) -> None:
        self.model = model
        self.feature_columns = feature_columns
        self.threshold = threshold
        self.cooldown = pd.Timedelta(minutes=cooldown_minutes)
        self.history_minutes = history_minutes
        self.history: dict[str, deque[Bar]] = {}
        self.last_alert_time: dict[str, pd.Timestamp] = {}
        self.latest_scores: dict[str, LiveScore] = {}
        self.alerts: list[dict] = []

    def ingest_bar(self, bar: Bar) -> None:
        buf = self.history.setdefault(bar.symbol, deque(maxlen=self.history_minutes))
        if buf and bar.close_time <= buf[-1].close_time:
            return  # out-of-order or duplicate bar; ignore rather than corrupt history order
        buf.append(bar)

    def ingest_batch(self, bars: list[Bar]) -> None:
        for bar in bars:
            self.ingest_bar(bar)

    def _bars_dataframe(self) -> pd.DataFrame:
        rows = [
            {
                "pair": pair, "minute": bar.close_time, "close": bar.close,
                "quote_volume": bar.volume_btc, "count": bar.trade_count,
                "taker_buy_quote": bar.taker_buy_btc,
            }
            for pair, buf in self.history.items()
            for bar in buf
        ]
        return pd.DataFrame(rows, columns=["pair", "minute", "close", "quote_volume", "count", "taker_buy_quote"])

    def score_latest(self) -> list[LiveScore]:
        """Compute cross-sectional features across every tracked pair's
        current buffer, score the latest shared minute, and apply the
        cooldown-gated alert threshold. Pairs with less than
        features.MIN_BASELINE_OBS minutes of real history are reported as
        "insufficient_history" with score=None rather than a misleading
        imputed value.
        """
        if not self.history:
            return []
        bars_df = self._bars_dataframe()
        if bars_df.empty:
            return []

        latest_minute = bars_df["minute"].max()
        results: list[LiveScore] = []

        short_history_pairs = {p for p, buf in self.history.items() if len(buf) < MIN_BASELINE_OBS}
        for pair in short_history_pairs:
            results.append(LiveScore(pair, None, "insufficient_history", None, False))

        scorable_df = bars_df[~bars_df["pair"].isin(short_history_pairs)]
        if scorable_df.empty:
            self.latest_scores = {r.pair: r for r in results}
            return results

        featured = compute_features(scorable_df)
        latest = featured.loc[featured["minute"] == latest_minute].reset_index(drop=True)
        if latest.empty:
            self.latest_scores = {r.pair: r for r in results}
            return results

        # A coin's own row can still have NaN features this early in its
        # buffer (robust_z's rolling windows need full history) even with
        # MIN_BASELINE_OBS minutes buffered -- exclude those too, rather
        # than let the model's internal imputer silently paper over them.
        has_nan = latest[self.feature_columns].isna().any(axis=1)
        valid = latest.loc[~has_nan].reset_index(drop=True)
        for pair in latest.loc[has_nan, "pair"]:
            results.append(LiveScore(pair, None, "insufficient_history", None, False))

        if not valid.empty:
            scores = _get_scores(self.model, valid[self.feature_columns])
            for i, row in valid.iterrows():
                pair = row["pair"]
                score = float(scores[i])
                minute = row["minute"]
                is_alert = False
                if score >= self.threshold:
                    last = self.last_alert_time.get(pair)
                    if last is None or (minute - last) >= self.cooldown:
                        is_alert = True
                        self.last_alert_time[pair] = minute
                        self.alerts.append({
                            "pair": pair, "score": score, "close_time": minute.isoformat(),
                        })
                results.append(LiveScore(pair, score, "scored", minute.isoformat(), is_alert))

        self.latest_scores = {r.pair: r for r in results}
        return results


async def fetch_backfill_bars(pair: str, minutes: int, client: httpx.AsyncClient) -> list[Bar]:
    """Real historical 1-minute closed bars for one pair, via Binance's
    public klines endpoint, enough to seed CrossSectionalScoringEngine's
    history buffer without waiting ~25 hours of live data to accumulate.
    """
    bars: list[Bar] = []
    remaining = minutes
    end_time_ms: int | None = None
    while remaining > 0:
        limit = min(remaining, BACKFILL_KLINE_LIMIT)
        params = {"symbol": pair, "interval": "1m", "limit": limit}
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        response = await client.get(f"{MARKET_API}/klines", params=params, timeout=20)
        response.raise_for_status()
        rows = response.json()
        if not rows:
            break
        for row in rows:
            open_time = datetime.fromtimestamp(row[0] / 1000, UTC)
            if open_time + timedelta(minutes=1) > datetime.now(UTC):
                continue  # the most recent REST kline may still be forming
            try:
                bars.append(Bar(
                    symbol=pair, close_time=open_time + timedelta(minutes=1),
                    close=float(row[4]), volume_btc=float(row[7]),
                    taker_buy_btc=float(row[10]), trade_count=int(row[8]),
                ))
            except ValueError:
                continue  # a malformed/invalid real row is skipped, not fabricated into validity
        remaining -= len(rows)
        end_time_ms = rows[0][0] - 1
        if len(rows) < limit:
            break
    bars.sort(key=lambda b: b.close_time)
    return bars


async def backfill_engine(engine: CrossSectionalScoringEngine, pairs: list[str], concurrency: int = 10) -> dict:
    """Backfill real history for every pair, concurrently but rate-limited.
    Returns {pair: n_bars_loaded} so callers can see real coverage per pair.
    """
    semaphore = asyncio.Semaphore(concurrency)
    counts: dict[str, int] = {}

    async with httpx.AsyncClient() as client:
        async def one(pair: str) -> None:
            async with semaphore:
                try:
                    bars = await fetch_backfill_bars(pair, engine.history_minutes, client)
                    engine.ingest_batch(bars)
                    counts[pair] = len(bars)
                except (httpx.HTTPError, ValueError) as exc:
                    counts[pair] = 0
                    logging.getLogger(__name__).warning("backfill failed for %s: %s", pair, exc)

        await asyncio.gather(*(one(p) for p in pairs))
    return counts
