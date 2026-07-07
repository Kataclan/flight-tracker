"""prices.json read/update: per combo x modality, best-ever + daily history."""
from __future__ import annotations

import json
from pathlib import Path


def load(path: Path) -> dict:
    data = json.loads(path.read_text() or "{}")
    data.setdefault("meta", {"currency": "EUR"})
    data.setdefault("combos", {})
    return data


def load_empty() -> dict:
    return {"meta": {"currency": "EUR"}, "combos": {}}


def record(data: dict, run_date: str, combo_id: str, modality: str,
           entry: dict | None) -> dict:
    """Append today's entry; update best. Returns comparison info
    {best_before, prev_entry, week_ago_entry}."""
    slot = data["combos"].setdefault(combo_id, {}).setdefault(
        modality, {"best": None, "history": []})
    hist = slot["history"]
    best_before = slot["best"]
    prev = hist[-1] if hist else None
    week_ago = next((h for h in reversed(hist)
                     if _days_between(h["date"], run_date) >= 6), None)

    if entry is not None:
        entry = {"date": run_date, **entry}
        # replace same-day entry on re-runs
        if hist and hist[-1]["date"] == run_date:
            hist[-1] = entry
        else:
            hist.append(entry)
        if best_before is None or entry["price"] < best_before["price"]:
            slot["best"] = {k: entry[k] for k in
                            ("date", "price", "source", "airlines", "out_date",
                             "ret_date") if k in entry}
    return {"best_before": best_before, "prev": prev, "week_ago": week_ago}


def record_watch(data: dict, run_date: str, watch_id: str,
                 entry: dict | None) -> dict | None:
    """Append today's entry for a watched flight ({found: false} when it didn't
    show up). Returns the previous day's entry (for delta/alerting)."""
    slot = data.setdefault("watches", {}).setdefault(watch_id, {"history": []})
    hist = slot["history"]
    prev = next((h for h in reversed(hist) if h["date"] != run_date), None)
    entry = {"date": run_date, **(entry or {"found": False})}
    if hist and hist[-1]["date"] == run_date:
        hist[-1] = entry
    else:
        hist.append(entry)
    return prev


def _days_between(d1: str, d2: str) -> int:
    from datetime import date
    return abs((date.fromisoformat(d2) - date.fromisoformat(d1)).days)


def save(data: dict, path: Path, run_date: str) -> None:
    data["meta"]["last_run"] = run_date
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
