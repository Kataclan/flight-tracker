"""Itinerary acceptance rules: max 1 stop per leg, max 5h layover."""
from __future__ import annotations

from .models import Itinerary


def acceptable(it: Itinerary, max_stops: int = 1, max_layover_min: int = 300) -> bool:
    for j in it.journeys:
        if j.stops > max_stops:
            return False
        if j.max_layover_min > max_layover_min:
            return False
    return True


def best(itineraries: list[Itinerary], max_stops: int = 1,
         max_layover_min: int = 300) -> Itinerary | None:
    ok = [i for i in itineraries
          if i.price_eur and acceptable(i, max_stops, max_layover_min)]
    return min(ok, key=lambda i: i.price_eur) if ok else None


def rejection_note(itineraries: list[Itinerary], max_stops: int = 1,
                   max_layover_min: int = 300) -> str | None:
    """When nothing passes the filters, explain the cheapest discarded option."""
    priced = [i for i in itineraries if i.price_eur]
    if not priced:
        return None
    ch = min(priced, key=lambda i: i.price_eur)
    worst_stops = max(j.stops for j in ch.journeys)
    worst_lay = max(j.max_layover_min for j in ch.journeys)
    why = []
    if worst_stops > max_stops:
        why.append(f"{worst_stops} escalas")
    if worst_lay > max_layover_min:
        why.append(f"espera {worst_lay // 60}h{worst_lay % 60:02d}")
    return (f"mejor descartada: {ch.price_eur:.0f}€ ({ch.source}, "
            f"{', '.join(ch.airlines)}) — {' y '.join(why) or 'filtros'}")
