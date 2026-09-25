# Panelbook 0.5.0.2

The first account is now the super admin. It can assign and remove ordinary admins. Admins can create and delete standard users, reset their passwords, and issue one-time or unlimited-use setup codes. Anyone with a code can create an account from the sign-in screen. Admins can revoke codes at any time.

Existing databases migrate automatically: the earliest existing administrator becomes super admin. Accounts, passwords, sessions, and homes remain in the `panelbook-data` volume. The default `compose.yaml` now pulls the prebuilt image. `compose.build.yaml` is available for source builds, and existing `compose.pull.yaml` deployments continue to work.

The Windows and hosted packages are `Panelbook-Portable-v0.5.0.2.zip` and `Panelbook-Server-v0.5.0.2.zip`.
