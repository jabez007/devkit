# Devkit Odoo specialization

Offline addon verification and opt-in Odoo 19 runtime tests. Offline checks
do not require an Odoo server, Go or Beads.

Install reviewed local wheels from the `mccann-hub-devkit` package family.
The unrelated PyPI `devkit` project is not this foundation. Installation
does not activate plugins, grant trust or write operator policy.

After selecting the required plugins in project configuration and explicitly
authorizing them in the external operator policy, use:

```sh
devkit --project /path/to/project run odoo.module.validate
```

For pre-commit hooks and CI, `devkit-odoo --project /path/to/project` runs the
same validator without plugin selection or operator policy. See
[running it as a hook](https://github.com/jabez007/devkit/blob/main/docs/Odoo_Validation.md#run-as-a-pre-commit-hook-or-ci-step).

`odoo.runtime.check` checks the Odoo executable and PostgreSQL connection.
`odoo.module.test` installs one selected addon on a generated database, runs
native Odoo tests, and drops the database. Both require explicit operator grants
for all effects. The standalone `devkit-odoo` entry point remains an offline
validator. See [runtime setup and limits](https://github.com/jabez007/devkit/blob/main/docs/Odoo_Validation.md#run-native-odoo-tests).

`odoo.module.version.check` compares all changed addons in the configured roots
against an explicit Git base commit. It requires increased explicit versions
for existing addons and an initial version for new addons. It uses separate
process and filesystem grants. See [version gate setup](https://github.com/jabez007/devkit/blob/main/docs/Odoo_Validation.md#require-a-version-bump-for-changed-addons).

See the [onboarding guide](https://github.com/jabez007/devkit/blob/main/docs/Getting_Started.md)
for developer and operator setup, and the
[plugin contract](https://github.com/jabez007/devkit/blob/main/docs/Plugin_Contract.md)
for extension authoring. The tested baseline is Linux and Python 3.12.

Licensed under GNU GPL version 3 or, at your option, any later version published
by the Free Software Foundation (`GPL-3.0-or-later`). See [LICENSE](LICENSE).
Registry publication and release ownership remain separate approvals; see the
[compatibility policy](https://github.com/jabez007/devkit/blob/main/docs/Compatibility.md).
