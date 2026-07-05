"""Markdown report + email-alert decision."""
from __future__ import annotations

import datetime as dt

from .models import Itinerary


def _fmt_journey(it: Itinerary) -> str:
    parts = []
    for j in it.journeys:
        route = " → ".join([j.segments[0].origin] +
                           [s.destination for s in j.segments])
        lay = j.max_layover_min
        dur = f"{j.duration_min // 60}h{j.duration_min % 60:02d}" if j.duration_min else "?"
        parts.append(f"{route} ({dur}" +
                     (f", escala {lay // 60}h{lay % 60:02d}" if lay else ", directo") + ")")
    scope = "" if it.detail_scope == "full" else " · detalle solo ida"
    return "; ".join(parts) + scope


def describe(it: Itinerary | None) -> dict | None:
    if it is None:
        return None
    return {
        "price": round(it.price_eur, 2),
        "source": it.source,
        "airlines": it.airlines,
        "detail": _fmt_journey(it),
        "virtual_interlining": it.virtual_interlining,
        "out_date": it.journeys[0].date if it.journeys else None,
        "ret_date": (it.journeys[-1].date if len(it.journeys) > 1
                     else (it.searched_dates[-1] if it.searched_dates and
                           len(it.searched_dates) > 1 else None)),
    }


def build(run_date: str, cfg: dict, results: dict, comparisons: dict,
          source_status: dict) -> tuple[str, dict]:
    """results[combo_id][modality] -> entry dict (from describe()) or None.
    comparisons[combo_id][modality] -> {best_before, prev, week_ago}.
    Returns (markdown, alert)."""
    th = cfg["thresholds"]
    weekday = dt.date.fromisoformat(run_date).weekday()
    reasons: list[str] = []
    title = cfg.get("title", "Vuelos BCN ↔ Japón")
    pax = cfg.get("passengers", 1)
    lines = [f"# {title} — {run_date}", ""]
    lines.append("Fuentes: " + ", ".join(f"{k}: {v}" for k, v in source_status.items()))
    if pax > 1:
        lines.append(f"\nPrecios totales para {pax} pasajeros.")
    lines.append("")
    lines.append("| Combinación | Modalidad | Precio | Aerolíneas | Detalle | VI | Fuente | Δ vs mejor | Δ vs semana |")
    lines.append("|---|---|---|---|---|---|---|---|---|")

    for combo_id, combo in cfg["combos"].items():
        for modality, mod_label in (("single", "billete único"),
                                    ("two_oneways", "2 solo-ida")):
            e = results.get(combo_id, {}).get(modality)
            cmp_ = comparisons.get(combo_id, {}).get(modality, {})
            best_before = cmp_.get("best_before")
            week_ago = cmp_.get("week_ago")
            if e is None or "no_data_note" in e:
                note = (e or {}).get("no_data_note") or "sin datos"
                lines.append(f"| {combo['label']} | {mod_label} | — sin opciones "
                             f"válidas | {note} | | | | | |")
                continue
            d_best = e["price"] - best_before["price"] if best_before else None
            d_week = e["price"] - week_ago["price"] if week_ago else None
            if best_before and d_best <= -th["drop_vs_best_eur"]:
                reasons.append(f"{combo['label']} ({mod_label}) baja "
                               f"{-d_best:.0f}€ vs mejor histórico "
                               f"({best_before['price']:.0f}€ → {e['price']:.0f}€)")
            if e["price"] < th["buy_below_eur"]:
                reasons.append(f"{combo['label']} ({mod_label}) por debajo del umbral "
                               f"de compra: {e['price']:.0f}€ < {th['buy_below_eur']}€")
            lines.append(
                f"| {combo['label']} | {mod_label} | **{e['price']:.0f}€** | "
                f"{', '.join(e['airlines'])} | {e['detail']} | "
                f"{'⚠️ sí' if e['virtual_interlining'] else 'no'} | {e['source']} | "
                f"{_delta(d_best)} | {_delta(d_week)} |")
        if combo.get("transfer_note"):
            lines.append(f"| ↳ _{combo['transfer_note']}_ | | | | | | | | |")

    if weekday == th["weekly_summary_weekday"]:
        reasons.append("resumen semanal (lunes)")

    all_prices = [e["price"] for c in results.values() for e in c.values()
                  if e and "price" in e]
    recommendation = _recommend(all_prices, th, reasons)
    lines += ["", f"## Recomendación", "", recommendation]

    alert = {
        "date": run_date,
        "send_email": bool(reasons),
        "reasons": reasons,
        "recommendation": recommendation,
    }
    return "\n".join(lines) + "\n", alert


def _delta(d: float | None) -> str:
    if d is None:
        return "n/a"
    if d == 0:
        return "="
    return f"{'▼' if d < 0 else '▲'} {abs(d):.0f}€"


def _recommend(prices: list[float], th: dict, reasons: list[str]) -> str:
    if not prices:
        return "Sin datos fiables hoy — no comprar, reintentar mañana."
    lo = min(prices)
    if lo < th["buy_below_eur"]:
        return (f"**COMPRAR YA**: hay opción a {lo:.0f}€, por debajo del umbral "
                f"de {th['buy_below_eur']}€.")
    if any("baja" in r for r in reasons):
        return (f"Bajada significativa detectada (mínimo hoy {lo:.0f}€). "
                f"Vigilar de cerca; comprar si baja de {th['buy_below_eur']}€.")
    return (f"Esperar: mínimo hoy {lo:.0f}€, sin bajada significativa ni precio "
            f"bajo el umbral de {th['buy_below_eur']}€.")
