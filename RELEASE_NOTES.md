# Panelbook 0.5.0.10

Protective devices now have a selector in the circuit detail view.

- Choose **Breaker itself**, an outlet / switch endpoint on that circuit, or **Custom / endpoint group**. The same choices are available for individual endpoint protection overrides.
- Selected breakers show their current panel and breaker position. Selected endpoints show their current name and reset location. A separate reset location can override the automatic location.
- Renaming an endpoint or changing its location updates linked protection records. Moving or deleting a referenced endpoint preserves its last name and reset location as a custom record and flags confirmed mappings for rechecking.
- Existing free-text protective devices are retained as custom records. Device selections save automatically, remain searchable, and are included in JSON imports and exports.

Existing accounts and data remain in the `panelbook-data` volume. In Arcane, redeploy the project to pull the updated image.

The Windows and hosted packages are `Panelbook-Portable-v0.5.0.10.zip` and `Panelbook-Server-v0.5.0.10.zip`. Windows portable users can install this release with **Check for updates**.
