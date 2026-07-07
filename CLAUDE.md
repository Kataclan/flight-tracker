# flight-tracker — rastreador diario de precios de vuelos

Rastreador diario de precios. **Todo el trabajo pesado lo hace
`run_tracker.py`** — NO buscar precios manualmente con WebFetch ni agentes:
ejecutar el script y leer sus salidas.

Un tracker activo:

| Tracker | Config | Salidas | Qué es |
|---|---|---|---|
| Japón | `config.json` | `prices.json`, `report.md`, `alert.json` | BCN↔Japón sep/oct 2026, 1 pax, 4 combos NGO/TYO × 2 modalidades |

## Rutina diaria (local, `./daily_run.sh` hace 2-4)

1. **Setup (solo si falta `.venv/`):**
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   .venv/bin/python -m playwright install chromium
   ```

2. **Ejecutar:**
   ```bash
   .venv/bin/python run_tracker.py
   ```
   - Tarda ~5-10 min. Exit 0 = OK; exit 2 = ninguna
     fuente devolvió datos (NO tocar `prices.json`, avisar del fallo).
   - Si Playwright/Chromium no funciona en el entorno (proxy que corta HTTPS
     del navegador), probar `--source google` (solo HTTP, sin navegador, suele
     pasar proxies).

3. **Salidas** (generadas por el script, no editarlas a mano):
   - `report.md` — tabla comparativa completa con fuente, tendencia y recomendación.
   - `alert.json` — `send_email` (bool) + `reasons` + `recommendation`.
   - `prices.json` — histórico actualizado (mejor precio + serie diaria por
     combinación × modalidad).

4. **Commit a `main`** (sí, directamente a main — decisión del usuario):
   ```bash
   git add prices.json report.md alert.json && git commit -m "prices: $(date +%F)" && git push origin main
   ```

5. **Alerta**: `alert.json:send_email == true` significa que hay algo que
   mirar (motivos en `reasons`); el resumen está en la tabla de `report.md`
   (fuente, fecha, Δ vs mejor histórico, Δ vs semana anterior y recomendación).

## Qué busca el script

- La config define fechas, pasajeros, umbrales, combos y notas de traslado.
  Modalidades siempre: billete único (RT/open-jaw) y 2 solo-ida.
- Japón: ida 16-17 sep 2026, vuelta 13-15 oct 2026; 4 combinaciones NGO/TYO.
- Filtros: máx 1 escala por trayecto, máx 5 h de espera. Si todo queda
  descartado, el informe muestra la mejor opción descartada y por qué.
- **Vuelos vigilados** (`config.json:watches`): itinerarios concretos
  (aerolínea + fechas + escala) con serie de precios propia en
  `prices.json:watches`, aunque no sean los más baratos de su combo. El
  informe añade la sección "Vuelos vigilados"; alerta si el precio varía ≥
  `alert_change_eur` vs día anterior (o vs `baseline_price_eur` el primer
  día) o si el vuelo desaparece de los resultados. Lógica en `tracker/watch.py`.
- Fuentes: **Trip.com** (primaria, vía Playwright reescribiendo el body del
  POST `FlightListSearchSSE` — ver `tracker/sources/tripcom.py`) y **Google
  Flights** (vía API protobuf `?tfs=`, sin navegador — ver
  `tracker/sources/google_flights.py`). Kiwi/Skyscanner: no implementados
  (Trip+Google cubren; añadir solo si ambas fallan de forma sostenida).

## Detalles técnicos que NO hay que redescubrir

- Trip.com devuelve HTTP 432 a fetch estático; funciona con Chromium headless.
  El multi-city (open-jaw) no tiene formato de URL estable: se consigue
  reescribiendo `searchCriteria.tripType=4` + `journeyInfoTypes` en el request
  interceptado. El header `token` NO está ligado al body — la reescritura es válida.
  tripType: 1=OW, 2=RT, 4=MT.
- Google Flights desde IP europea redirige a muro de consentimiento: se evita
  con la cookie `SOCS`. El parser de `fast_flights` upstream casca con
  itinerarios sin precio; usamos un fork tolerante en `google_flights.py`.
- En búsquedas RT/MT ambas fuentes devuelven "fare-first": precio total del
  billete pero detalle solo del primer trayecto (`detail_scope=first_journey_only`).
  El precio es correcto; solo falta el detalle de la vuelta.
- Los precios de ambas fuentes son EUR totales (tasas incluidas).

## Arquitectura de ejecución (desde 2026-07-07: solo local)

Todo corre en el Mac del usuario: `./daily_run.sh` (manual, sin job
programado — decisión suya) ejecuta el tracker y pushea `prices.json`,
`report.md`, `alert.json` a main. Log: `daily_run.log`.

La antigua rutina cloud de claude.ai se eliminó: su entorno no tenía red
hacia las fuentes (proxy cortaba Chromium y el HTTP impersonado de Google)
y gastaba tokens solo para mirar si el repo había cambiado. Si se quiere
revisar alertas, hacerlo desde una sesión local leyendo `alert.json`.
