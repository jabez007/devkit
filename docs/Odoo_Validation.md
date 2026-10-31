# Offline Odoo validation

`odoo.module.validate` checks Odoo 19 manifest literals and direct dependency
presence without importing addons or installing an Odoo server. Its check ID is
`odoo.manifests`. The foundation's command registry, policy, invocation and
evidence mechanisms apply unchanged.

## Start with custom addons

Install the foundation and Odoo specialization, authorize the command using the
[operator policy example](../README.md#authorize-commands), and put this in
`devkit.toml`:

```toml
plugins = ["odoo"]

[options.odoo]
addons_paths = ["addons"]

[profiles]
static = ["odoo.manifests"]
```

Run `devkit --project /absolute/project check static`, or invoke the command
with `devkit --project /absolute/project run odoo.module.validate`.
A custom addon depending on `base` and `sale` can pass the implemented static
checks while reporting those dependencies as **unknown**. Success does not claim
that the addon is installable. Use `--json` before the subcommand for structured
relationships, scanned paths, examined modules, diagnostics and unchecked areas.

## Inventory and strict checks

| Dependency status | Meaning |
| --- | --- |
| `resolved` | A module with this name and a manifest exists in the configured inventory. |
| `missing` | No such module exists, and an explicit completeness claim covers its name. |
| `unknown` | No such module exists, and the configured inventory cannot establish absence. |
| `invalid` | The declaration is not a list of valid module identifiers, or an entry is invalid. |

The default inventory is incomplete. A completed directory scan does **not** make
it complete. Add dependency sources explicitly, relative to the selected project:

```toml
[options.odoo]
addons_paths = ["custom/addons", "vendor/odoo/addons", "vendor/oca/server-tools"]
strict_dependencies = true

[options.odoo.inventory]
complete = false
complete_prefixes = ["acme_"]
```

Here an absent `acme_sales` is missing; an absent `base` is unknown. Prefixes are
literal, case-sensitive module-name prefixes, not globs. They assert completeness
for those names across the combined inventory. Set `complete = true` only when
all relevant module sources are present. Devkit records this as an **operator or
project configuration claim**, not an independently established fact. Do not set
it merely to turn an unknown result into a failure or to silence blocked checks.
Repository configuration describes the inventory; it cannot grant permissions.

All paths must remain within the authorized project/workspace root. Vendor
external sources there, or choose a common workspace root containing separate
checkouts and authorize that root explicitly. Absolute paths, parent traversal,
escaping symlinks and duplicate module names are rejected. Directory order does
not select a winner for duplicate names. No dependencies are downloaded.

Invalid declarations and confirmed missing dependencies fail, including when
`strict_dependencies` is false. Strict mode additionally returns **blocked** with
`INCOMPLETE_INVENTORY` when a dependency is unknown. A defect takes precedence
over incomplete coverage; structured findings retain both. A strict check can
succeed with an incomplete inventory if all examined direct dependencies resolve.
Unavailable scan paths block validation; a partial or failed scan never classifies
absent modules as missing.

Invocation arguments override the corresponding Odoo options, replacing an
entire nested inventory object when supplied:

```sh
devkit --project /absolute/project --json run odoo.module.validate --args '{"strict_dependencies":true}'
devkit --project /absolute/project --json run odoo.module.validate --args '{"module":"acme_sales"}'
```

## Evidence and coverage

Domain data schema `validation_schema_version = "1.1"` adds:

- `inventory`: declared completeness, prefixes, claim basis, scan completion,
  scanned paths and counts, bounds, and the resolution basis `manifest_presence`.
- `modules[].dependencies`: direct relationships with name, status, resolved
  relative path, and whether the dependency was implicit.
- `modules[].external_dependencies`: Python and binary requirements, reported as
  unknown without importing packages or searching for executables.
- `dependency_counts`: relationship counts, including repeated dependency names
  used by different addons; `inspection_complete` distinguishes partial results.
- `not_checked`: runtime, database, XML semantics, assets, external requirements,
  transitive dependencies and dependency cycles.

Existing module fields, including `unresolved_dependencies`, remain available.
That legacy list contains valid missing **and** unknown module names; consumers
must use the new relationships to distinguish them. The generic result envelope
and plugin API do not change. Consumers expecting strict unresolved dependencies
to be a module failure must handle `blocked / INCOMPLETE_INVENTORY` instead.

A resolved relationship verifies manifest presence only. Selecting one module
checks that module's manifest, not its dependencies' manifests or transitive
closure. Omitted or empty `depends` implies `base`, except for `base` itself,
following the [pinned Odoo 19 loader](https://github.com/odoo/odoo/blob/005e0a0eb7ef80cd15b0c82b570b2b0843181ba2/odoo/modules/module.py).
`auto_install` triggers are checked against normalized dependencies; optional
bridge modules still need their declared dependencies if installed. External
requirements do not turn into Odoo module dependencies and are not checked by
strict module-dependency validation.

Inspection is bounded to 32 addons paths, 10,000 total directory entries, 1,000
modules, 256 KiB and 10,000 AST nodes per manifest, and a bounded findings payload.
Cancellation and deadline checks occur during scanning and inspection. Limit
errors retain partial coverage without claiming complete inspection. Narrow
`addons_paths` or select one module when necessary. Data/demo references are
checked for containment and file presence, not XML validity. Manifest expressions
are never executed, and addon Python files are never imported.

Retrieve saved evidence without loading a plugin:

```sh
devkit --project /absolute/project --json runs list
devkit --project /absolute/project --json runs show <run-uuid>
```

`doctor` checks the foundation, plugin activation and declared environment
prerequisites. Run `odoo.module.validate` to inspect addons paths and manifests.
Static validation does not establish runtime Odoo compatibility, installation,
upgrade behavior or database correctness.
