"""Build the query plan from config: which searches to run for each combo/modality."""
from __future__ import annotations

from itertools import product


def single_ticket_queries(cfg: dict, quick: bool = False) -> list[dict]:
    """One query per combo per (out_date, ret_date). RT when airports mirror,
    multi-city (open-jaw) otherwise."""
    out_dates = cfg["outbound_dates"][:1] if quick else cfg["outbound_dates"]
    ret_dates = cfg["return_dates"][1:2] if quick else cfg["return_dates"]
    queries = []
    for combo_id, combo in cfg["combos"].items():
        o, r = combo["outbound"], combo["return"]
        is_rt = o["from"] == r["to"] and o["to"] == r["from"]
        for od, rd in product(out_dates, ret_dates):
            queries.append({
                "combo_id": combo_id,
                "modality": "single",
                "trip_type": 2 if is_rt else 4,
                "journeys": [
                    {"from": o["from"], "to": o["to"], "date": od},
                    {"from": r["from"], "to": r["to"], "date": rd},
                ],
            })
    return queries


def oneway_queries(cfg: dict, quick: bool = False) -> list[dict]:
    """Deduplicated one-way legs across all combos (each combo reuses them)."""
    out_dates = cfg["outbound_dates"][:1] if quick else cfg["outbound_dates"]
    ret_dates = cfg["return_dates"][1:2] if quick else cfg["return_dates"]
    seen = set()
    queries = []
    for combo in cfg["combos"].values():
        for leg, dates in ((combo["outbound"], out_dates), (combo["return"], ret_dates)):
            for d in dates:
                key = (leg["from"], leg["to"], d)
                if key in seen:
                    continue
                seen.add(key)
                queries.append({
                    "leg_key": f"{leg['from']}-{leg['to']}",
                    "modality": "oneway",
                    "trip_type": 1,
                    "journeys": [{"from": leg["from"], "to": leg["to"], "date": d}],
                })
    return queries
