"""Google Flights source via the embedded ?tfs= protobuf API (no browser).

Uses fast-flights to build the query URL, fetches with curl_cffi (Chrome TLS
impersonation + EU consent cookie so google.com doesn't bounce to the consent
wall), and parses the ds:1 payload with a tolerant fork of fast_flights.parser
(the upstream one crashes on entries without a price).

For RT/MT the result lists first-leg options priced at the full-ticket total
(detail_scope="first_journey_only"), same as Trip.com's fare-first flow.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time

from curl_cffi import requests as creq
from fast_flights import FlightQuery, Passengers, create_query
from selectolax.lexbor import LexborHTMLParser

from ..models import Itinerary, Journey, Segment

log = logging.getLogger("tracker.google")

CONSENT_COOKIES = {"SOCS": "CAISHAgBEhJnd3NfMjAyNDA4MjYtMF9SQzIaAmVzIAEaBgiA_LC2Bg"}
TRIP_TYPE = {1: "one-way", 2: "round-trip", 4: "multi-city"}


def _fmt_dt(date_t, time_t) -> str:
    try:
        return f"{date_t[0]:04d}-{date_t[1]:02d}-{date_t[2]:02d} " \
               f"{(time_t[0] or 0):02d}:{(time_t[1] or 0) if len(time_t) > 1 and time_t[1] else 0:02d}"
    except Exception:
        return "?"


def _layover_min(prev_arr_date, prev_arr_time, dep_date, dep_time) -> int | None:
    try:
        a = dt.datetime(*prev_arr_date, prev_arr_time[0] or 0,
                        (prev_arr_time[1] if len(prev_arr_time) > 1 and prev_arr_time[1] else 0))
        d = dt.datetime(*dep_date, dep_time[0] or 0,
                        (dep_time[1] if len(dep_time) > 1 and dep_time[1] else 0))
        return int((d - a).total_seconds() // 60)
    except Exception:
        return None


def _parse_payload(payload) -> list[Itinerary]:
    airline_names = {}
    try:
        for code, name in payload[7][1][1]:
            airline_names[code] = name
    except Exception:
        pass

    out: list[Itinerary] = []
    for group_idx in (2, 3):  # 2 = "best", 3 = "other"
        try:
            group = payload[group_idx][0]
        except (IndexError, TypeError):
            continue
        if not group:
            continue
        for k in group:
            flight = k[0]
            try:
                price = float(k[1][0][1])
            except (IndexError, TypeError):
                continue  # no price shown -> useless for tracking
            segs = []
            prev = None
            codes: set[str] = set()
            for s in flight[2]:
                fn = s[22] if len(s) > 22 and s[22] else None
                code = fn[0] if fn else "?"
                codes.add(code)
                layover = None
                if prev is not None:
                    layover = _layover_min(prev[21], prev[10], s[20], s[8])
                segs.append(Segment(
                    origin=s[3], destination=s[6],
                    depart=_fmt_dt(s[20], s[8]), arrive=_fmt_dt(s[21], s[10]),
                    flight_no=f"{fn[0]} {fn[1]}" if fn else "?",
                    airline_code=code,
                    airline_name=(fn[3] if fn and len(fn) > 3 and fn[3]
                                  else airline_names.get(code, code)),
                    duration_min=s[11],
                    layover_before_min=layover,
                ))
                prev = s
            if not segs:
                continue
            journey = Journey(origin=segs[0].origin, destination=segs[-1].destination,
                              date=segs[0].depart[:10], segments=segs,
                              duration_min=flight[9] if len(flight) > 9 and
                              isinstance(flight[9], int) else None)
            out.append(Itinerary(
                source="google-flights",
                price_eur=price,
                journeys=[journey],
                airlines=sorted(airline_names.get(c, c) for c in codes),
                virtual_interlining=False,  # Google lists published fares/alliances
                detail_scope="full",  # fixed up by caller for RT/MT
            ))
    return out


def search(journeys: list[dict], trip_type: int, max_stops: int = 1,
           retries: int = 2) -> list[Itinerary]:
    """journeys item: {"from": "BCN", "to": "NGO", "date": "2026-09-16"}"""
    q = create_query(
        flights=[FlightQuery(date=j["date"], from_airport=j["from"],
                             to_airport=j["to"]) for j in journeys],
        trip=TRIP_TYPE[trip_type],
        seat="economy",
        passengers=Passengers(adults=1),
        currency="EUR",
        language="en",
        max_stops=max_stops,
    )
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = creq.get("https://www.google.com/travel/flights", params=q.params(),
                         impersonate="chrome", cookies=CONSENT_COOKIES, timeout=60)
            parser = LexborHTMLParser(r.text)
            script = parser.css_first(r"script.ds\:1")
            if script is None:
                raise RuntimeError(f"no ds:1 script (HTTP {r.status_code}, "
                                   f"len {len(r.text)}) — consent wall or block")
            data = script.text().split("data:", 1)[1].rsplit(",", 1)[0]
            if data.endswith("errorHasStatus: true"):
                return []
            its = _parse_payload(json.loads(data))
            for it in its:
                it.searched_dates = [j["date"] for j in journeys]
                if len(journeys) > 1:
                    it.detail_scope = "first_journey_only"
            return its
        except Exception as e:
            last_err = e
            log.warning("google attempt %d failed for %s: %s", attempt + 1, journeys, e)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"google flights failed for {journeys}: {last_err}")
