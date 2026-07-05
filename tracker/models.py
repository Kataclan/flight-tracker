"""Shared data models for flight search results."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class Segment:
    """One flight (no stops) inside a journey."""
    origin: str
    destination: str
    depart: str            # "YYYY-MM-DD HH:MM"
    arrive: str
    flight_no: str
    airline_code: str
    airline_name: str
    duration_min: int
    layover_before_min: int | None = None  # connection time at `origin` (None for first segment)


@dataclass
class Journey:
    """One direction of travel (outbound or return), possibly with a connection."""
    origin: str
    destination: str
    date: str              # departure date "YYYY-MM-DD"
    segments: list[Segment] = field(default_factory=list)
    duration_min: int | None = None

    @property
    def stops(self) -> int:
        return max(len(self.segments) - 1, 0)

    @property
    def max_layover_min(self) -> int:
        return max((s.layover_before_min or 0 for s in self.segments), default=0)


@dataclass
class Itinerary:
    """One priced option from one source. For fare-first sources (Trip.com RT/MT,
    Google RT/MT) only the first journey carries segment detail; the price is
    still the full-ticket total."""
    source: str
    price_eur: float
    journeys: list[Journey] = field(default_factory=list)
    airlines: list[str] = field(default_factory=list)
    virtual_interlining: bool = False
    seats_left: int | None = None
    detail_scope: str = "full"  # "full" | "first_journey_only"
    searched_dates: list[str] | None = None  # dates the query asked for

    def to_dict(self) -> dict:
        return asdict(self)
