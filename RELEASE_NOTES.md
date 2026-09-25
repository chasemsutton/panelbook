# Panelbook 0.5.0.3

New users can now create accounts from the sign-in screen without a setup code by default. The super admin can turn on **Require a setup code for new accounts** in **Admin settings**. When enabled, registration requires a valid one-time or unlimited-use code. Admins can still create accounts directly and revoke codes at any time.

Existing databases gain the new setting with codes optional. Accounts, passwords, sessions, and homes remain in the `panelbook-data` volume. Redeploy with the existing volume to update.

The Windows and hosted packages are `Panelbook-Portable-v0.5.0.3.zip` and `Panelbook-Server-v0.5.0.3.zip`.
