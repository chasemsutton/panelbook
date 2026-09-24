# Panelbook 0.5.0.1

The Windows portable app now enables **Close server when all tabs close** by default for local-only workspaces. This fits the invisible launcher: after the last browser tab closes, Panelbook stops automatically. The setting can still be turned off; the first launch of an existing local workspace enables it once, and later changes persist.

The updater now understands four-part version numbers for future releases. Version 0.5.0 cannot discover this tag because its release check only accepts three-part versions. To move from 0.5.0, close Panelbook, extract the new portable ZIP, copy your existing `data/` folder into it, and run the new top-level `Panelbook.exe`. JSON export and import remain available.

The Windows and hosted packages are `Panelbook-Portable-v0.5.0.1.zip` and `Panelbook-Server-v0.5.0.1.zip`.
