## Install

1. Download `MarstekMonitor-…-win64.zip` below and unzip it anywhere, for example to `C:\Programs`.
   Keep the whole `MarstekMonitor` folder together.
2. Run `MarstekMonitor.exe`. The exe is not code-signed, so Windows SmartScreen may show
   "Windows protected your PC": click **More info → Run anyway**.
3. When Windows asks whether the app may use private networks, allow it. Otherwise the
   battery's replies are blocked.
4. Turn on **Local API** for the battery in the Marstek app (default UDP port 30000).
   The PC must be on the same network.

To update, exit the app from the tray menu and replace the folder. Settings and history stay in
`%APPDATA%\MarstekMonitor`.

The user guide for this version is in the `docs` folder next to the exe: `user-guide.md` (English)
and `user-guide.uk.md` (Ukrainian).

The app only reads from the battery. It never changes any battery setting.
