#!/usr/bin/env python3
"""Daily BCN↔Japan flight price tracker.

Usage:
  python run_tracker.py                 # full run: trip.com primary, google cross-check
  python run_tracker.py --quick         # 1 date pair only (smoke test)
  python run_tracker.py --source google # skip trip.com (e.g. env without browser)
  python run_tracker.py --dry-run       # don't write prices.json

Outputs: report.md, alert.json, updated prices.json.
Exit code 0 = ran (check alert.json:send_email), 2 = no source produced data.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

from tracker import filters, history, plan, report
from tracker.models import Itinerary
from tracker.sources import google_flights, tripcom

ROOT = Path(__file__).parent
log = logging.getLogger("tracker")


def merge_two_oneways(cfg: dict, out_opts: list[Itinerary], ret_opts: list[Itinerary],
                      max_stops: int, max_layover: int) -> Itinerary | None:
    """Cheapest acceptable outbound+return pair whose dates respect trip_days."""
    outs = [i for i in out_opts if i.price_eur and
            filters.acceptable(i, max_stops, max_layover)]
    rets = [i for i in ret_opts if i.price_eur and
            filters.acceptable(i, max_stops, max_layover)]
    pair = None
    for o in outs:
        for r in rets:
            if not plan.trip_days_ok(cfg, o.journeys[0].date, r.journeys[0].date):
                continue
            if pair is None or o.price_eur + r.price_eur < \
                    pair[0].price_eur + pair[1].price_eur:
                pair = (o, r)
    if pair is None:
        return None
    o, r = pair
    return Itinerary(
        source=o.source if o.source == r.source else f"{o.source} + {r.source}",
        price_eur=o.price_eur + r.price_eur,
        journeys=o.journeys + r.journeys,
        airlines=sorted(set(o.airlines + r.airlines)),
        virtual_interlining=True,  # two separate tickets = self-transfer risk
        detail_scope="full",
    )


def run_source_trip(single_qs, ow_qs, concurrency, adults) -> tuple[dict, dict, str]:
    queries = [(q["journeys"], q["trip_type"]) for q in single_qs + ow_qs]
    try:
        res = tripcom.search_many_sync(queries, concurrency=concurrency, adults=adults)
    except Exception as e:
        log.error("trip.com source failed entirely: %s", e)
        return {}, {}, f"FALLO ({e})"
    singles, oneways = {}, {}
    for q, r in zip(single_qs + ow_qs, res):
        if q["modality"] == "single":
            singles.setdefault(q["combo_id"], []).extend(r)
        else:
            key = (q["leg_key"], q["journeys"][0]["date"])
            oneways.setdefault(key, []).extend(r)
    n = sum(len(v) for v in list(singles.values()) + list(oneways.values()))
    empty = sum(1 for r in res if not r)
    return singles, oneways, f"OK ({n} itinerarios, {empty}/{len(res)} búsquedas vacías)"


def run_source_google(single_qs, ow_qs, max_stops, adults) -> tuple[dict, dict, str]:
    singles, oneways = {}, {}
    n = fails = 0
    for q in single_qs + ow_qs:
        try:
            r = google_flights.search(q["journeys"], q["trip_type"],
                                      max_stops=max_stops, adults=adults)
        except Exception as e:
            log.warning("google query failed: %s", e)
            fails += 1
            continue
        n += len(r)
        if q["modality"] == "single":
            singles.setdefault(q["combo_id"], []).extend(r)
        else:
            key = (q["leg_key"], q["journeys"][0]["date"])
            oneways.setdefault(key, []).extend(r)
    status = f"OK ({n} itinerarios)" if fails == 0 else \
             f"PARCIAL ({n} itinerarios, {fails} búsquedas fallidas)"
    if n == 0:
        status = "FALLO (0 itinerarios)"
    return singles, oneways, status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json",
                    help="config file (outputs get suffixed with its 'name' field)")
    ap.add_argument("--quick", action="store_true", help="single date pair smoke test")
    ap.add_argument("--source", choices=["trip", "google", "all"], default="all")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--date", default=None, help="override run date YYYY-MM-DD")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    cfg = json.loads((ROOT / args.config).read_text())
    run_date = args.date or dt.date.today().isoformat()
    max_stops = cfg["max_stops_per_leg"]
    max_layover = cfg["max_layover_minutes"]
    adults = cfg.get("passengers", 1)
    suffix = f"_{cfg['name']}" if cfg.get("name") else ""
    prices_path = ROOT / f"prices{suffix}.json"
    report_path = ROOT / f"report{suffix}.md"
    alert_path = ROOT / f"alert{suffix}.json"

    single_qs = plan.single_ticket_queries(cfg, quick=args.quick)
    ow_qs = plan.oneway_queries(cfg, quick=args.quick)
    log.info("plan: %d single-ticket + %d one-way queries per source",
             len(single_qs), len(ow_qs))

    source_status: dict[str, str] = {}
    singles: dict[str, list[Itinerary]] = {}
    oneways: dict[tuple, list[Itinerary]] = {}

    if args.source in ("trip", "all"):
        s, o, st = run_source_trip(single_qs, ow_qs, args.concurrency, adults)
        source_status["trip.com"] = st
        for k, v in s.items():
            singles.setdefault(k, []).extend(v)
        for k, v in o.items():
            oneways.setdefault(k, []).extend(v)

    if args.source in ("google", "all"):
        s, o, st = run_source_google(single_qs, ow_qs, max_stops, adults)
        source_status["google-flights"] = st
        for k, v in s.items():
            singles.setdefault(k, []).extend(v)
        for k, v in o.items():
            oneways.setdefault(k, []).extend(v)

    got_data = any(singles.values()) or any(oneways.values())
    if not got_data:
        log.error("no source produced any itinerary — aborting without touching history")
        alert_path.write_text(json.dumps({
            "date": run_date, "send_email": False,
            "reasons": [], "error": "sin datos de ninguna fuente",
            "source_status": source_status}, ensure_ascii=False, indent=1))
        return 2

    hist = history.load(prices_path) if prices_path.exists() else \
        history.load_empty()
    results: dict[str, dict] = {}
    comparisons: dict[str, dict] = {}

    for combo_id, combo in cfg["combos"].items():
        results[combo_id] = {}
        comparisons[combo_id] = {}

        combo_singles = singles.get(combo_id, [])
        best_single = filters.best(combo_singles, max_stops, max_layover)
        entry = report.describe(best_single)
        comparisons[combo_id]["single"] = history.record(
            hist, run_date, combo_id, "single", entry)
        if entry is None:
            note = filters.rejection_note(combo_singles, max_stops, max_layover)
            entry = {"no_data_note": note} if note else None
        results[combo_id]["single"] = entry

        out_leg = f"{combo['outbound']['from']}-{combo['outbound']['to']}"
        ret_leg = f"{combo['return']['from']}-{combo['return']['to']}"
        out_opts = [i for (lk, _d), v in oneways.items() if lk == out_leg for i in v]
        ret_opts = [i for (lk, _d), v in oneways.items() if lk == ret_leg for i in v]
        best_two = merge_two_oneways(cfg, out_opts, ret_opts, max_stops, max_layover)
        entry2 = report.describe(best_two)
        comparisons[combo_id]["two_oneways"] = history.record(
            hist, run_date, combo_id, "two_oneways", entry2)
        if entry2 is None:
            notes = []
            for label, opts in (("ida", out_opts), ("vuelta", ret_opts)):
                if not filters.best(opts, max_stops, max_layover):
                    n = filters.rejection_note(opts, max_stops, max_layover)
                    notes.append(f"{label}: {n or 'sin resultados'}")
            entry2 = {"no_data_note": "; ".join(notes)} if notes else None
        results[combo_id]["two_oneways"] = entry2

    md, alert = report.build(run_date, cfg, results, comparisons, source_status)
    alert["source_status"] = source_status
    report_path.write_text(md)
    alert_path.write_text(
        json.dumps(alert, ensure_ascii=False, indent=1) + "\n")
    if not args.dry_run:
        history.save(hist, prices_path, run_date)

    print(md)
    print(f"send_email={alert['send_email']} reasons={alert['reasons']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
