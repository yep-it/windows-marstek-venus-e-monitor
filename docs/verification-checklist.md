# Real-device verification (read-only)

These checks settle the open questions V1–V5 from the design spec. None of them changes a battery
setting. Before you start, turn on **Settings → Advanced → Record raw data** and click **Save**.
The raw responses go to `%APPDATA%\MarstekMonitor\logs\raw-YYYYMMDD.jsonl`.

## V1: Power sign (while charging)

1. Wait until the battery is charging. In UPS mode the Marstek app shows a charge power of 1000 W.
2. Open the monitor's **Now** tab.
   - If it shows **↓ Charging · ≈1 000 W**, the default is right.
   - If it shows **↑ Supplying**, set **Advanced → Power sign → − means charging** and click **Save**.
3. Repeat while the battery is supplying power, to confirm the opposite direction.

## V2: Counter units

1. Compare **Energy → Charged / Discharged (lifetime)** with the totals in the Marstek app.
2. If they differ by a factor of 10, 100 or 1000, pick the matching **Advanced → Counter unit**.
3. When the numbers match, tick **Counter units verified**. This shows the efficiency card and
   removes the "not verified" note.

## V3 + V5: What a grid outage looks like

1. Make sure something is plugged into the battery's backup (off-grid) socket.
2. Switch off the battery's grid supply for 1–2 minutes (breaker or plug), then switch it back on.
3. Keep the raw log for that time window. The question is: which of `ongrid_power` and
   `offgrid_power` change, and how?
4. Turn on **Advanced → Outage detection (experimental)** only after the heuristic in
   `core/outage.py` has been confirmed against the recording or adjusted to match it.

## V4: Mode (answered)

The API reports `"Manual"` while the Marstek app shows UPS, so the app does not use the mode at all.
