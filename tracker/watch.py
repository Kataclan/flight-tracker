"""Watched flights: track one specific itinerary (airline + dates + via) so it
keeps its own daily price series even when it's not the cheapest of its combo."""
from __future__ import annotations

from .models import Itinerary


def _ret_date(it: Itinerary) -> str | None:
    if len(it.journeys) > 1:
        return it.journeys[-1].date
    if it.searched_dates and len(it.searched_dates) > 1:
        return it.searched_dates[-1]
    return None


def matches(it: Itinerary, m: dict) -> bool:
    if "airline" in m and not any(m["airline"].lower() in a.lower()
                                  for a in it.airlines):
        return False
    if "out_date" in m and (not it.journeys or it.journeys[0].date != m["out_date"]):
        return False
    if "ret_date" in m and _ret_date(it) != m["ret_date"]:
        return False
    if "via" in m:
        # connection airports (fare-first results only carry outbound detail,
        # which is where the via constraint lives anyway)
        stops = {s.destination for j in it.journeys for s in j.segments[:-1]}
        if m["via"] not in stops:
            return False
    return True


def find(itineraries: list[Itinerary], m: dict) -> Itinerary | None:
    """Cheapest itinerary matching the watch criteria, or None."""
    ok = [i for i in itineraries if i.price_eur and matches(i, m)]
    return min(ok, key=lambda i: i.price_eur) if ok else None
