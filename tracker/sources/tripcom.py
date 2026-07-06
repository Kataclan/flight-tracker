"""Trip.com source via Playwright + in-flight request-body rewriting.

Trip.com's flight list page fires a POST to /restapi/soa2/27015/FlightListSearchSSE
with a signed `token` header. The signature is NOT bound to the request body, so we
load any search page and rewrite the JSON body in-flight (playwright route) to query
exactly the journeys we want, including multi-city/open-jaw (tripType=4) which has
no stable URL format.

tripType values: 1 = one-way, 2 = round-trip, 4 = multi-city.

For RT/MT the fare-first response lists outbound journeys with the *total* ticket
price (cheapest completion); return-leg detail is not included (detail_scope =
"first_journey_only").
"""
from __future__ import annotations

import asyncio
import json
import logging

from playwright.async_api import async_playwright

from ..models import Itinerary, Journey, Segment

log = logging.getLogger("tracker.tripcom")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

TRIP_TYPE = {1: "ow", 2: "rt", 4: "mt"}


def _base_url(journeys: list[dict], adults: int = 1) -> str:
    j0 = journeys[0]
    url = (f"https://www.trip.com/flights/showfarefirst?dcity={j0['from'].lower()}"
           f"&acity={j0['to'].lower()}&ddate={j0['date']}")
    if len(journeys) > 1:
        url += f"&rdate={journeys[-1]['date']}&triptype=rt"
    else:
        url += "&triptype=ow"
    return url + f"&class=y&quantity={adults}&locale=en-XX&curr=EUR"


def _journey_payload(journeys: list[dict]) -> list[dict]:
    return [{"journeyNo": i + 1, "departDate": j["date"], "departCode": j["from"],
             "arriveCode": j["to"], "departAirport": "", "arriveAirport": ""}
            for i, j in enumerate(journeys)]


def _parse_sse(text: str) -> dict | None:
    """Return the data chunk with the most itineraries from an SSE body."""
    best = None
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            d = json.loads(line[5:])
        except json.JSONDecodeError:
            continue
        n = len(d.get("itineraryList") or [])
        if best is None or n > len(best.get("itineraryList") or []):
            best = d
    return best


def _to_itineraries(data: dict) -> list[Itinerary]:
    airline_names = {a["code"]: a["name"] for a in (data.get("airlineList") or [])}
    out: list[Itinerary] = []
    n_journeys_searched = len((data.get("basicInfo") or {}).get(
        "searchCondition", {}).get("searchJourneys", []) or [])
    for it in data.get("itineraryList") or []:
        journeys = []
        vi = False
        codes: set[str] = set()
        for j in it.get("journeyList") or []:
            segs = []
            for s in j.get("transSectionList") or []:
                if s.get("transportType") != "FLIGHT":
                    vi = True  # train/bus link = self-managed or unusual connection
                fi = s.get("flightInfo") or {}
                code = fi.get("airlineCode", "?")
                codes.add(code)
                if s.get("transSplit"):
                    vi = True
                segs.append(Segment(
                    origin=s["departPoint"]["airportCode"],
                    destination=s["arrivePoint"]["airportCode"],
                    depart=s["departDateTime"][:16],
                    arrive=s["arriveDateTime"][:16],
                    flight_no=fi.get("flightNo", "?"),
                    airline_code=code,
                    airline_name=airline_names.get(code, code),
                    duration_min=s.get("duration"),
                    layover_before_min=s.get("transferDuration"),
                ))
            if not segs:
                continue
            journeys.append(Journey(
                origin=segs[0].origin, destination=segs[-1].destination,
                date=segs[0].depart[:10], segments=segs,
                duration_min=j.get("duration"),
            ))
        if not journeys:
            continue
        policies = it.get("policies") or []
        prices = [p["price"]["totalPrice"] for p in policies
                  if p.get("price", {}).get("totalPrice")]
        if not prices:
            continue
        seats = min((p.get("seatCount") or 9) for p in policies)
        out.append(Itinerary(
            source="trip.com",
            price_eur=float(min(prices)),
            journeys=journeys,
            airlines=sorted(airline_names.get(c, c) for c in codes),
            virtual_interlining=vi,
            seats_left=seats,
            detail_scope="full" if len(journeys) >= max(n_journeys_searched, 1)
                          else "first_journey_only",
        ))
    return out


async def _run_query(browser, journeys: list[dict], trip_type: int,
                     adults: int = 1, timeout_s: int = 45) -> list[Itinerary]:
    ctx = await browser.new_context(locale="en-US", user_agent=UA,
                                    viewport={"width": 1440, "height": 900})
    page = await ctx.new_page()
    responses: list[str] = []

    async def rewrite(route):
        try:
            body = json.loads(route.request.post_data)
            sc = body["searchCriteria"]
            sc["tripType"] = trip_type
            sc["journeyInfoTypes"] = _journey_payload(journeys)
            sc["passengerInfoType"] = {"adultCount": adults, "childCount": 0,
                                       "infantCount": 0}
            await route.continue_(post_data=json.dumps(body))
        except Exception:
            await route.continue_()

    async def on_response(resp):
        if "FlightListSearchSSE" in resp.url:
            try:
                responses.append(await resp.text())
            except Exception:
                pass

    await page.route("**/FlightListSearchSSE*", rewrite)
    page.on("response", on_response)
    try:
        await page.goto(_base_url(journeys, adults), wait_until="domcontentloaded",
                        timeout=timeout_s * 1000)
        waited = 0
        while waited < timeout_s:
            await page.wait_for_timeout(3000)
            waited += 3
            if responses and _parse_sse(responses[-1]) and \
               (_parse_sse(responses[-1]).get("itineraryList")):
                # give late SSE chunks a moment, then stop
                await page.wait_for_timeout(3000)
                break
    finally:
        await ctx.close()

    merged: dict[str, Itinerary] = {}
    for txt in responses:
        data = _parse_sse(txt)
        if not data:
            continue
        ret = (data.get("head") or {}).get("retMsg")
        if ret:
            log.warning("trip.com retMsg=%s for %s", ret, journeys)
        for it in _to_itineraries(data):
            it.searched_dates = [j["date"] for j in journeys]
            key = "|".join(f"{s.flight_no}@{s.depart}" for j in it.journeys
                           for s in j.segments)
            if key not in merged or it.price_eur < merged[key].price_eur:
                merged[key] = it
    return list(merged.values())


async def search_many(queries: list[tuple[list[dict], int]],
                      concurrency: int = 3,
                      adults: int = 1,
                      headless: bool = True) -> list[list[Itinerary]]:
    """queries: list of (journeys, trip_type). journeys item:
    {"from": "BCN", "to": "NGO", "date": "2026-09-16"}"""
    results: list[list[Itinerary]] = [[] for _ in queries]
    sem = asyncio.Semaphore(concurrency)
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless, args=["--disable-blink-features=AutomationControlled"])

        done = 0

        async def worker(i, q):
            nonlocal done
            journeys, trip_type = q
            route = " ".join(f"{j['from']}-{j['to']} {j['date']}" for j in journeys)
            async with sem:
                try:
                    for attempt in (1, 2):
                        try:
                            r = await _run_query(browser, journeys, trip_type, adults)
                            if r:
                                results[i] = r
                                return
                            log.info("empty result attempt %d for %s", attempt, journeys)
                        except Exception as e:
                            log.warning("trip.com attempt %d failed for %s: %s",
                                        attempt, journeys, e)
                        await asyncio.sleep(3)
                finally:
                    done += 1
                    log.info("trip.com %d/%d: %s -> %d itinerarios",
                             done, len(queries), route, len(results[i]))

        await asyncio.gather(*(worker(i, q) for i, q in enumerate(queries)))
        await browser.close()
    return results


def search_many_sync(queries, concurrency: int = 3,
                     adults: int = 1) -> list[list[Itinerary]]:
    return asyncio.run(search_many(queries, concurrency=concurrency, adults=adults))
