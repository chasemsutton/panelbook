# Panelbook 0.3.3

Fixes Windows portable updates hanging at “Installing the update” without restarting Panelbook. The updater now launches its helper in a hidden window, which allows the script to run and restart the server.

The updater smoke test now uses the same process launch flags as the app and covers a real 0.3.1 to 0.3.3 update.

**Manual update required from 0.2.0 through 0.3.2.** Close Panelbook, extract the new ZIP into a new folder, copy your existing `data/` folder beside its `Panelbook.cmd`, and run the new launcher. Keep the old folder as a backup until your data appears. In-app updates work from 0.3.3 onward.
