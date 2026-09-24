# Panelbook

An offline residential electrical panel directory. Extract the archive and open `panelbook.html` in a modern browser. Keep the five files in one directory; no server, build step, account, or internet connection is needed.

## Updates

Version 0.1.3 checks for updates quietly once a day while the app is open and the internet is available. Choose **Stable** or **Beta** beside **Check for updates** to set the channel or check immediately. Stable checks published releases; Beta includes prereleases and stable releases. The chosen channel is remembered on this device. All panel features work offline.

When a newer release exists, click **Install update** in a browser that supports folder access. The first time, select the directory containing `panelbook.html` and approve write access. The app remembers that folder, so later updates usually install with one click. It downloads the five release files, checks their SHA-256 hashes against the release manifest, and replaces the files in that directory. The app restores the previous files if writing fails. Keep the app in the same directory when you reopen it so its browser storage remains available. On browsers without folder access, **Download release** remains available. Keep a JSON export of important data before making changes to your local files. Update checks and downloads require access to GitHub.

## Homes and panels

Choose a home or location at the top. Add homes, rename the selected home, and add main panels. **Subpanel from here** asks for a name and an explicit feeder circuit from the open panel; it never chooses one automatically. A feeder must be an assigned, rated 240 V circuit, and each feeder can supply only one linked subpanel. Add the feeder circuit and its amp rating first. Each subpanel appears beneath its source panel, including nested subpanels. Click any panel card to open it or use **Open source panel** to go back. Feeder links follow the circuit record if its breaker assignment changes. If a feeder circuit is deleted, its subpanel remains visible with a feeder warning so you can reconnect it.

Beside the panel name and spaces, **Make subpanel** requires a source panel and eligible feeder. **Make main panel** removes the feeder link while keeping its child panels attached. **Delete panel** asks for confirmation and also deletes descendant subpanels with their circuits and points. The last main panel in a home cannot be deleted until another main panel is added. A circuit in a subpanel cannot be rated above its feeder circuit, and lowering a feeder rating below an existing subpanel circuit is blocked. Any previously saved subpanel without a valid feeder is clearly marked for correction.

Each panel has its own 12–42 spaces, breaker types, circuits, points, and printed directory. The panel name and spaces are edited beside the physical map.

## Entering a panel

1. Choose the number of spaces in pairs and check the actual bus diagram and approved breaker positions.
2. Click a position and select single pole, double pole, tandem, or quad tandem. A double spans two positions in one column. A tandem splits one position into `a` and `b`. A quad spans two positions and offers upper outer `5a`, central two-pole `5b/7a`, and lower outer `7b` when placed at position 5. The outer segments are 25% of its height each; the two-pole center is 50%.
3. Add circuits with a breaker, friendly name, voltage, amperage, wire gauge, and label preference. New circuits start unassigned with 120 V. Double-pole and quad center assignments accept 240 V; singles, tandems, and quad outer assignments accept 120 V. An incompatible voltage change unassigns the circuit. An occupied breaker cannot be converted if doing so would lose a circuit.
4. Add points of consumption with a permanent number, friendly name, location/description, and linked circuit. Point numbers remain fixed when other points move or are deleted.
5. Choose whether a breaker displays its circuit name or linked outlet/switch names. Click table headings to sort in either direction. The selected sort and direction persist after closing the page.

## Print and backup

Click **Print / PDF** to open a popup with **Current panel**, **Current panel + subpanels**, **All panels in home**, and **Cancel**. The printed panel pages show physical breaker order. Each panel's detail tables follow the current on-screen sort order and show the active sort column and ▲/▼ direction. The browser's print dialog can save as PDF. Every panel's directory starts on a new page, with its circuit and point details starting on the next page when present.

Click **Export JSON** to choose **Current panel**, **Current home**, **Everything**, or **Cancel**. JSON files include their scope. Importing a panel lets you replace an existing panel or add a new main or subpanel. Replacing preserves the target panel’s place in the home and clears direct child feeder assignments so they cannot silently point to a different circuit; importing a home adds it as another home with its subpanel feeder links preserved; importing everything replaces the full collection after confirmation. Existing full-collection version 4 JSON backups remain importable. Browser storage saves changes automatically. Existing local version 3 panel data opens as the first main panel once.

## Checks and limits

- Two-space breakers need an available position below in the same column. Shrinking a panel cannot remove assigned positions or split a two-space breaker. Converting a quad requires moving circuits that cannot fit in the new type. Deleting a circuit leaves its points unassigned with their numbers intact.
- Leg totals add breaker ratings, not measured load. A double-pole or quad center rating counts once on A and once on B. “Balanced” means a difference of at most 10% of the larger total.
- Wire warnings use copper 60 °C reference values: 14 AWG 15 A; 12 AWG 20 A; 10 AWG 30 A; 8 AWG 40 A; 6 AWG 55 A; 4 AWG 70 A; 2 AWG 95 A; 1/0 AWG 125 A. Blank values are unchecked. Installation conditions and applicable rules may change what is permitted.
- Tandem and quad compatibility depends on the exact panel and breaker. Verify the manufacturer's labeling and consult a qualified electrician for installation decisions.

## Files

`panelbook.html`, `styles.css`, `app.js`, `README.md`, and `release.json`.
