from dataclasses import asdict, dataclass, field


@dataclass
class PriceEstimate:
    provider: str
    estimated_monthly_cost_usd: float
    hourly_cost_usd: float | None
    pricing_type: str
    pricing_source: str
    currency: str = "USD"
    region: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
