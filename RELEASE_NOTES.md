# Panelbook 0.5.0.9

Added circuit detail views, mapping verification, and protection and reset location records.

- Click an assigned breaker or **Details** beside a circuit to see its ratings, connected outlets / switches, upstream feeders, and supplied subpanels.
- Mark breaker and outlet / switch mappings as **Unverified**, **Confirmed**, or **Needs rechecking**. Confirmation records the date and person. Changed assignments flag confirmed mappings for rechecking and retain the previous confirmation details.
- Record GFCI, AFCI, or combined protection, the protective device, and its reset location. Individual outlets / switches can override the circuit record. All separately recorded reset locations appear near the top of the circuit detail view.
- Verification and protection records save automatically, are searchable, and are included in JSON imports and exports. Older version 4 imports start with unverified mappings and unknown protection. Viewers can open the detail view with read-only access.

Existing accounts and data remain in the `panelbook-data` volume. In Arcane, redeploy the project to pull the updated image.

The Windows and hosted packages are `Panelbook-Portable-v0.5.0.9.zip` and `Panelbook-Server-v0.5.0.9.zip`.
