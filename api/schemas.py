"""B1 platform contract plus the retained manual demo contract."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from pumpradar.engine import Bar

Mode = Literal["demo_stub", "mock", "research_ranker"]
Horizon = Literal["1", "3", "5", "10", "30", "60"]
Risk = Annotated[float, Field(ge=0, le=1)]


class Provenance(BaseModel):
    scorer: Mode
    mock: bool
    model_version: str | None = None
    notice: str


class Market(BaseModel):
    symbol: str
    price: float = Field(gt=0)
    change_24h_pct: float | None
    volume_24h_quote: float | None
    quote_asset: str
    scored: bool
    model_score: float | None = None


class MarketsResponse(Provenance):
    as_of: datetime | None
    markets: list[Market]


class RiskAlert(BaseModel):
    id: str
    pair: str
    time: datetime
    horizon: Horizon
    risk: Risk
    reasons: list[str]
    mock: bool


class CoinRisk(BaseModel):
    pair: str
    tier: Literal["low", "medium", "high"]
    risk: dict[Horizon, Risk]
    level: Literal["Normal", "Watch", "Alert"]
    alert: RiskAlert | None
    sparkline: list[Risk]


class Candle(BaseModel):
    time: datetime
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume_quote: float | None


class RiskPoint(BaseModel):
    time: datetime
    risk: dict[Horizon, Risk]


class Driver(BaseModel):
    label: str
    value: float


class CoinResponse(Provenance):
    pair: str
    market: Market
    current: CoinRisk | None
    bars: list[Candle]
    risk_series: list[RiskPoint]
    alerts: list[RiskAlert]
    drivers: list[Driver]


class PricesEvent(Provenance):
    sequence: int
    as_of: datetime
    markets: list[Market]


class RadarTick(Provenance):
    sequence: int
    as_of: datetime
    rows: list[CoinRisk]
    newAlerts: list[RiskAlert]


class ReplayEvent(BaseModel):
    event_id: str
    pair: str
    t_onset: datetime
    t_telegram: datetime | None
    era: Literal["mock", "test"]
    first_alert_lead_minutes: float | None
    rank_at_onset: int | None


class ReplayEventsResponse(Provenance):
    events: list[ReplayEvent]


class ReplayDetailResponse(Provenance):
    event: ReplayEvent
    frames: list[RadarTick]
    bars: list[Candle]


class HonestyResponse(Provenance):
    status: Literal["unavailable"]
    precision: float | None = None
    recall: float | None = None
    median_lead_minutes: float | None = None
    hit_at_5: float | None = None
    false_alerts_per_hour: float | None = None
    alert_budget_per_hour: float | None = None
    limitations: list[str]


class AuditPoint(BaseModel):
    horizon_min: int
    feature_set: Literal["clean", "full"]
    model: str
    random_ap: float | None
    honest_ap: float | None
    inflation_ap: float | None
    honest_ci_low: float | None = None
    honest_ci_high: float | None = None
    honest_prevalence: float | None = None


class FeatureImportance(BaseModel):
    feature: str
    importance_mean: float
    importance_std: float


class ExperimentAResponse(BaseModel):
    status: Literal["historical_experiment_a"] = "historical_experiment_a"
    source_commit: str
    source_artifacts: list[str]
    notice: str
    points: list[AuditPoint]
    importance_by_feature_set: dict[Literal["clean", "full"], list[FeatureImportance]]
    limitations: list[str]


class ExperimentBPoint(BaseModel):
    horizon_min: int
    model: str
    test_ap: float | None
    test_prevalence: float | None
    hit_at_5: float | None
    n_test_events: int


class ExperimentBResponse(BaseModel):
    status: Literal["historical_experiment_b"] = "historical_experiment_b"
    source_commit: str
    source_artifacts: list[str]
    notice: str
    selected_model: str
    selection_horizon_min: int
    points: list[ExperimentBPoint]
    limitations: list[str]


class LiveModelCoin(BaseModel):
    pair: str
    score: float | None
    scoring_status: Literal["scored", "insufficient_history"]
    as_of: datetime | None
    is_alert: bool


class LiveModelScoresResponse(BaseModel):
    status: Literal["unavailable", "warming_up", "scored"]
    model_version: str | None
    score_type: str
    threshold: float | None
    threshold_status: str | None
    n_tracked_pairs: int
    coins: list[LiveModelCoin]
    notice: str


class BarInput(BaseModel):
    symbol: str
    close_time: datetime
    close: float = Field(gt=0)
    volume_btc: float = Field(ge=0)
    taker_buy_btc: float = Field(ge=0)
    trade_count: int = Field(ge=0)

    def as_bar(self) -> Bar:
        return Bar(**self.model_dump())


class BatchInput(BaseModel):
    bars: list[BarInput] = Field(min_length=1)


class ReplayInput(BaseModel):
    bars: list[BarInput]
    onset_time: datetime | None = None
    threshold: float = Field(default=0.8, ge=0, le=1)


class DemoScore(BaseModel):
    symbol: str
    close_time: datetime
    score: float | None
    relative_volume: float | None
    buy_share: float
    status: Literal["warming_up", "demo_stub"]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    scorer: Mode
    mock: bool = False
    model_loaded: bool = False
    market_feed: Literal["mock", "not_connected"] = "not_connected"
    price_interval_seconds: int = 2
    score_interval_seconds: int | None = None


class BatchResponse(BaseModel):
    minute: datetime
    coins: list[DemoScore]


class RadarResponse(BaseModel):
    scorer: Mode
    minute: datetime | None
    coins: list[DemoScore]
    mock: bool = False
    model_version: str | None = None
    notice: str = "Legacy five-bar demo heuristic. Frozen Experiment B rankings are at /scores/live."
    rows: list[CoinRisk] = Field(default_factory=list)
    sequence: int | None = None


class AlertRecord(BaseModel):
    symbol: str
    close_time: datetime
    score: float
    status: Literal["demo_stub"]


class AlertsResponse(BaseModel):
    scorer: Mode
    alerts: list[AlertRecord | RiskAlert]
    mock: bool = False
    notice: str = "Demo heuristic alerts; no measured false-alert guarantee."


class ReplayResponse(BaseModel):
    scorer: Literal["demo_stub"]
    frames: list[DemoScore]
    alerts: list[DemoScore]
    first_pre_onset_alert: DemoScore | None
    lead_minutes: float | None
