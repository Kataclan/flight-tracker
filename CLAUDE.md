# flight-tracker — BCN ↔ Japón (sep/oct 2026)

Rastreador diario de precios de vuelos. **Todo el trabajo pesado lo hace
`run_tracker.py`** — la rutina NO debe buscar precios manualmente con WebFetch
ni agentes: ejecuta el script, lee sus salidas y decide el email.

## Pasos de la rutina diaria

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
   - Tarda ~5-10 min (34 búsquedas × 2 fuentes). Exit 0 = OK; exit 2 = ninguna
     fuente devolvió datos (NO tocar prices.json, avisar del fallo).
   - Si Playwright/Chromium no funciona en el entorno (proxy que corta HTTPS
     del navegador), probar `--source google` (solo HTTP, sin navegador, suele
     pasar proxies). Indicar en el email que Trip.com no estuvo disponible.

3. **Salidas** (generadas por el script, no editarlas a mano):
   - `report.md` — tabla comparativa completa con fuente, tendencia y recomendación.
   - `alert.json` — `send_email` (bool) + `reasons` + `recommendation`.
   - `prices.json` — histórico actualizado (mejor precio + serie diaria por
     combinación × modalidad).

4. **Commit a `main`** (sí, directamente a main — decisión del usuario):
   ```bash
   git add prices.json report.md alert.json && git commit -m "prices: $(date +%F)" && git push origin main
   ```

5. **Email**: enviar SOLO si `alert.json:send_email == true`. El cuerpo debe
   incluir la tabla de `report.md` (ya trae fuente, fecha, Δ vs mejor histórico,
   Δ vs semana anterior y recomendación). Los motivos están en `reasons`.

## Qué busca el script

- Ida 16-17 sep 2026, vuelta 13-15 oct 2026; 4 combinaciones de aeropuertos
  (NGO/TYO en cada sentido) × 2 modalidades (billete único RT/open-jaw y
  2 solo-ida). Definido en `config.json` (fechas, umbrales, notas de traslado).
- Filtros: máx 1 escala por trayecto, máx 5 h de espera. Si todo queda
  descartado, el informe muestra la mejor opción descartada y por qué.
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
