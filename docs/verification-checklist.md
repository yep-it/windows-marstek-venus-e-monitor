# Real-device verification (read-only)

These checks settle the open questions V1–V5 from the design spec. None of them changes a battery
setting. Before you start, turn on **Settings → Advanced → Record raw data** and click **Save**.
The raw responses go to `%APPDATA%\MarstekMonitor\logs\raw-YYYYMMDD.jsonl`.

## V1: Power sign (answered 2026-10-01)

While charging from the grid the battery reports a **negative** `ongrid_power` (about −1000 W at the
UPS charge power of 1000 W). The default is now **− means charging**; older settings files are
migrated automatically. A load on the backup socket shows only in `offgrid_power`.

## V2: Counter units

1. Compare **Energy → Charged / Discharged (lifetime)** with the totals in the Marstek app.
2. If they differ by a factor of 10, 100 or 1000, pick the matching **Advanced → Counter unit**.
3. When the numbers match, tick **Counter units verified**. This shows the efficiency card and
   removes the "not verified" note.

## V3 + V5: What a grid outage looks like (answered 2026-10-01)

- **Grid disconnected, PC on the backup socket:** `ongrid_power` 0, `offgrid_power` 72–149 W, stored
  energy falling. This is what the experimental outage detection looks for.
- **Grid reconnected, same load:** `ongrid_power` about −1000 W (charging), so no false outage.
- **The backup socket is not counted** in `total_grid_output_energy`; the app uses power × time instead.

- **Grid connected, battery full, same load:** `ongrid_power` is 0 here too, but the stored energy stays
  at 5120 Wh: the grid passes power straight through. The app therefore counts a backup load as
  "battery supplying" only while the battery is below full; in a real outage starting at 100 % this
  shows up after about 3 minutes.

Outage detection (**Advanced → Outage detection**, then **Grid lost / restored**) can now be turned on.
An outage with nothing plugged into the backup socket cannot be detected from the battery data.

## V4: Mode (answered)

The API reports `"Manual"` while the Marstek app shows UPS, so the app does not use the mode at all.
