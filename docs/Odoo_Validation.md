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

Domain data schema 1.1 introduced these fields, which remain in 1.4:

- `inventory`: declared completeness, prefixes, claim basis, scan completion,
  scanned paths and counts, bounds, and the resolution basis `manifest_presence`.
- `modules[].dependencies`: direct relationships with name, status, resolved
  relative path, and whether the dependency was implicit.
- `modules[].external_dependencies`: Python and binary requirements, reported as
  unknown without importing packages or searching for executables.
- `dependency_counts`: relationship counts, including repeated dependency names
  used by different addons; `inspection_complete` distinguishes partial results.
- `not_checked`: runtime, database, XML semantics, assets, external requirements,
  transitive dependencies and cycles through uninspected manifests or unresolved dependencies.

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
checked for containment and file presence. In v0.3, declared XML also receives
the bounded syntax and reference inspection described below. Manifest expressions
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

## Representative validation

The [synthetic repositories](../tests/fixtures/odoo/README.md) cover custom-only,
internal, external OCA-style, complete, duplicate, invalid, unsafe and optional
addon cases, plus the XML and CSV scenarios below. Twenty-six CLI scenarios assert
statuses and relationships, text output,
persisted evidence and `runs show`. The same script runs against a separately
installed Odoo-only wheel. Python/CLI/MCP parity tests also cover successful,
blocked and failed dependency results and policy revocation.

On October 31, 2026, devkit-odoo 0.2.0 evaluated the public
[OCA/server-tools 19.0 snapshot](https://github.com/OCA/server-tools/tree/389daeb98a8e21fe11594bdddef873bb07d0cb61).
The checkout remained clean. No addon Python code was imported, no server was
started, and no dependencies were installed. Configuration and evidence were
stored outside the checkout. These commands were used against that snapshot:

```sh
devkit --project /tmp/devkit-v02-oca-server-tools --json run odoo.module.validate --args '{"addons_paths":["."],"strict_dependencies":false}'
devkit --project /tmp/devkit-v02-oca-server-tools --json run odoo.module.validate --args '{"addons_paths":["."],"strict_dependencies":true}'
```

| Observation | Ordinary check | Strict check |
| --- | --- | --- |
| Modules examined | 30 | 30 |
| Resolved direct relationships | 2 | 2 |
| Unknown direct relationships | 30 | 30 |
| Missing / invalid relationships | 0 / 0 | 0 / 0 |
| External requirements left unverified | 8 | 8 |
| Result / CLI exit | success / 0 | blocked / 2 |

The strict reason was `INCOMPLETE_INVENTORY`. Returned results matched persisted
evidence, which was retrieved through `runs show`. Both records identified source
revision `389daeb98a8e21fe11594bdddef873bb07d0cb61` with `dirty=false`. This is a
snapshot evaluation, not a certification of OCA modules or their runtime behavior.
No private client repositories or production instances were accessed.

## XML syntax inspection in v0.3

The existing command now parses XML files declared in manifest `data` and `demo`
after checking their paths. No configuration change is required. Malformed XML
fails with `INVALID_XML`; diagnostics identify the module-relative file and
one-based line and column. XML syntax is separate from Odoo view, model and
runtime validity.

DTD declarations, unsupported encodings, unreadable XML and exhausted inspection
limits block coverage. A DTD is unsupported, not automatically malformed XML.
The parser does not load external entities or resources. UTF-8, UTF-16 and
Latin-1 have acceptance coverage. UTF-32 is explicitly unsupported and blocks
inspection rather than producing a malformed-XML finding. CSV and other declared file types retain path
checks without XML parsing.

devkit-odoo 0.3.0 uses additive specialization data schema 1.2. Update the exact
plugin trust version and any approved wheel digest when upgrading. Previously
passing projects with malformed XML now fail by design. Each module has `xml.files`, with
path, data/demo phase, status, reason and diagnostic location, plus `xml.complete`.
Top-level `xml_counts` totals valid, invalid and blocked files. `xml_parser`
records the linked Expat version. Earlier dependency
fields and strict-dependency behavior remain unchanged. A confirmed defect takes
precedence over blocked coverage, but both findings remain in evidence.

Limits apply to each invocation: 256 XML files, 16 MiB total XML bytes and 100,000
elements. Each file is capped at 1 MiB and nesting at 128 elements. Cancellation
and deadlines are checked between parse chunks and elements. Cancellation and
deadline expiry use the foundation's standard result, which does not retain partial
domain findings. The overall findings
size limit still applies. These restrictions do not replace maintaining Python
and its linked Expat library. See the [Python XML guidance](https://docs.python.org/3.12/library/xml.html).

### Literal XML references

`xml.files` also reports `definitions`, `references` and `unexamined` operations.
References carry their raw value, normalized `xml_id`, attribute, source location,
status, reason and, when resolved, the target definition location. Top-level
`xml_reference_counts` aggregates resolved and unknown references. Source columns
are one-based Expat offsets; multibyte text may use byte-oriented offsets.

The supported subset is direct loader `record`, `menuitem` and `template`
operations under `odoo`, `openerp` or `data`. Definitions become available after
an operation ends. Direct record `field ref`, menu `parent` and `action`, and
template `inherit_id` and `website_id` attributes are examined. Definitions and
references inside embedded view/template markup are not treated as loader
operations. Nested record/menu operations and group membership are outside this
subset. Dynamic `eval`, search and context expressions are never evaluated.

A resolved reference has an earlier same-module literal definition in the
examined load sequence. This is static source evidence, not proof that a database
record exists or that an Odoo operation succeeds. Repeated definitions are
retained as potential updates. Definitions under explicit `noupdate`,
`forcecreate`, context or user conditions cannot establish unconditional presence.
Foreign-module updates are reported as external references, not new definitions.

Data files precede demo files, and each phase preserves manifest order. Demo
references can use earlier data definitions; data cannot rely on demo. Unknown
reasons distinguish forward definitions, demo-only definitions, conditional
sources, external modules, unsupported literals and IDs absent from scanned XML.
Dynamic operations, unparsed files and skipped non-XML files interrupt static
certainty about earlier definitions. Later lookups may report `unverified_effects`.

Module-inventory completeness does not imply XML-ID completeness. CSV data,
model metadata, hooks and installed records can supply IDs. Unknown XML references
therefore do not fail validation, and `strict_dependencies` continues to govern
module dependencies only. Inspect `unexamined` and `skipped_files` alongside the
reference counts. `xml.complete` describes file inspection, not complete runtime
reference verification. Reference collection is limited to 4,000 events per
invocation; exceeding the limit blocks inspection and discards partial events
from the affected file.

### v0.3 public repository evaluation

On October 31, 2026, devkit-odoo 0.3.0 evaluated two public 19.0 snapshots with
`addons_paths=["."]`, both with ordinary and strict module-dependency validation.
The CLI results matched persisted evidence and `runs show`. Both checkouts
remained clean. No addon code, Odoo server or private repository was used.

| Snapshot | Modules | XML files valid | XML references resolved / unknown | Unexamined operations | Skipped non-XML files |
| --- | --- | --- | --- | --- | --- |
| [OCA/server-tools](https://github.com/OCA/server-tools/tree/389daeb98a8e21fe11594bdddef873bb07d0cb61) | 30 | 62 | 52 / 76 | 28 | 8 |
| [OCA/sale-workflow](https://github.com/OCA/sale-workflow/tree/b2cb74591c66882b91264106abc5229e200f5bff) | 103 | 237 | 52 / 363 | 99 | 25 |

Neither snapshot produced malformed or blocked XML findings. Ordinary validation
succeeded; strict dependency validation blocked with `INCOMPLETE_INVENTORY`.
Their module dependencies respectively contained 30 and 126 unknown relationships.
Unknown XML references included external modules, IDs not present in scanned XML,
conditional definitions and lookups after unverified operations. These are
coverage findings, not demonstrated defects in the public projects.

The local parser reported `expat_2.6.3`. This records the tested environment and
does not certify that parser version against every vulnerability. Keep the
runtime maintained. The fixture suite also proves malformed XML fails and DTD
inspection blocks, so successful public runs are not the only acceptance evidence.

To reproduce after configuring plugin trust and an exact project grant:

```sh
devkit --project /absolute/path/to/checkout --json run odoo.module.validate --args '{"addons_paths":["."]}'
devkit --project /absolute/path/to/checkout --json run odoo.module.validate --args '{"addons_paths":["."],"strict_dependencies":true}'
```

## CSV inspection in v0.4

This milestone ships devkit-odoo 0.4.0 with specialization data schema 1.3. Update
exact plugin trust and any approved wheel digest when upgrading. The foundation,
Go and MCP package versions and the generic result envelope are unchanged.

Manifest-declared CSV files now receive bounded inspection through
`odoo.module.validate`. CSV and XML declarations share the existing literal
reference resolver and preserve manifest file order, row order and data/demo
separation. No new command, configuration flag, runtime dependency or generic
plugin interface is required.

The supported CSV subset uses UTF-8, commas and double quotes. It supports flat
fields, `id` declarations, and direct `field:id` or `field/id` references. Quoted
commas, escaped quotes and multiline values are supported. Translation columns
containing `@` are ignored as in the pinned Odoo loader. Empty rows and rows with
only translation values are ignored before width checks. Empty IDs create no
inferred identity; repeated IDs remain possible updates.

The inspector does not execute cells or return ordinary record values. It records
headers, nonempty row count, source locations and XML-ID findings. CSV reference
locations use a one-based physical start line and field index, not a character
column. The model name comes from the filename, following the loader convention;
model existence and field types are not verified.

Earlier same-module CSV declarations can resolve later XML references. CSV
references can use earlier XML declarations or CSV rows. Definitions become
available after the row's references. Foreign IDs, forward references and
ambiguous values remain unknown. A quoted comma-separated reference value is not
split without relational field metadata. Successful source inspection does not
establish database record existence, permissions or successful import.

| Finding | Result |
| --- | --- |
| Empty file without a header, or bytes invalid as UTF-8 | `failed / INVALID_CSV`, matching the pinned loader's input requirements. |
| Duplicate/aliased headers, nested import paths, nonempty irregular rows or UTF-8 BOM | `blocked / CSV_UNSUPPORTED`. |
| Quoting rejected by strict CSV inspection | `blocked / CSV_UNSUPPORTED`; Odoo uses a permissive reader, so rejection is not a confirmed import defect. |
| Unreadable file | `blocked / CSV_UNAVAILABLE`. |
| File, byte, row, field, column or reference-event limit | `blocked / CSV_LIMIT`. |
| Unknown literal reference | Advisory finding; does not fail or block by itself. |

A file that fails or blocks contributes no partial definitions or references.
Later files cannot resolve IDs from that file. Other findings remain available.
Confirmed defects take precedence over incomplete coverage in the command status.
Strict module-dependency validation retains its existing meaning; module inventory
completeness does not imply XML-ID completeness.

CSV has its own invocation budget: 256 files, 16 MiB total bytes, 10,000 data rows
including ignored rows, and 4,000 reference events. Each file is limited to 1 MiB,
128 columns and 65,536 characters per field. Selected header names must be at
most 256 characters. The existing result-size limit also applies. The inspector leaves Python's process-global CSV field-size limit
unchanged; a lower ambient parser limit can also block inspection. Cancellation
and deadlines use the shared foundation contract.

Specialization data schema 1.3 adds `modules[].csv`, `csv_counts`,
`csv_reference_counts` and `csv_limits`. CSV file results contain `headers`,
`row_count`, `model`, definitions, references and diagnostics. Existing XML fields
remain; their reference targets can now point to CSV declarations. The legacy
`xml.skipped_files` location contains files neither inspector examines. CSV files
no longer appear there. XML's existing `not_in_scanned_xml` reason remains for
compatibility; it does not assert absence from runtime data. New CSV findings use
`not_in_scanned_data` for references absent from the inspected source inventory.

The [pinned CSV loader](https://github.com/odoo/odoo/blob/005e0a0eb7ef80cd15b0c82b570b2b0843181ba2/odoo/tools/convert.py)
and [field-path importer](https://github.com/odoo/odoo/blob/005e0a0eb7ef80cd15b0c82b570b2b0843181ba2/odoo/orm/models.py)
define this subset. Nested imports, relational cardinality, runtime conversions,
model metadata and hooks remain outside coverage.

### v0.4 public repository evaluation

On October 31, 2026, devkit-odoo 0.4.0 rechecked the same pinned public snapshots
used for v0.3. Configuration and evidence stayed outside the checkouts. Both
ordinary and strict runs matched persisted evidence and `runs show`; Git reported
both checkouts clean. No addon code or runtime service was executed.

| Snapshot | CSV files inspected | Nonempty CSV rows | CSV references resolved / unknown | XML references resolved / unknown |
| --- | --- | --- | --- | --- |
| [OCA/server-tools](https://github.com/OCA/server-tools/tree/389daeb98a8e21fe11594bdddef873bb07d0cb61) | 8 | 50 | 2 / 98 | 52 / 76 |
| [OCA/sale-workflow](https://github.com/OCA/sale-workflow/tree/b2cb74591c66882b91264106abc5229e200f5bff) | 25 | 57 | 0 / 114 | 52 / 363 |

All 33 CSV files passed the implemented structural checks. They had previously
been skipped. Ordinary validation succeeded; strict module-dependency validation
still blocked on incomplete module inventories. Existing XML resolution counts
were unchanged. The public result establishes added CSV coverage and explicit
reference diagnostics, not a reduction in those projects' unknown XML references.
Synthetic mixed-format fixtures establish the new cross-format resolution cases.
Generated model IDs and external modules remain outside the source inventory.

## Dependency cycles in v0.5

`odoo.module.validate` checks dependency edges among the manifests it inspects.
A confirmed loop fails with `DEPENDENCY_CYCLE`, even when unrelated dependencies
remain unknown. A self-dependency is also a cycle. Human output shows one closed
path, for example `acme_sales -> acme_stock -> acme_sales`. Review `depends` in
those modules' `__manifest__.py` files and remove the circular requirement.

The graph uses the existing resolved dependency relationships, including implicit
`base` dependencies. It deduplicates repeated declarations for graph analysis;
the original declaration counts remain unchanged. Missing, unknown and invalid
edges cannot create a cycle. A completeness claim does not supply any graph edges.

Only inspected manifests enter the graph. Selecting `--args '{"module":"acme_sales"}'`
still inspects that module alone. A resolved dependency whose manifest was not
inspected is excluded from graph analysis. Run without the module selector to
inspect the configured inventory. Neither choice downloads dependencies or
executes addon code.

Schema 1.4 adds `dependency_graph`:

| Field | Meaning |
| --- | --- |
| `status` | `not_checked`, `cycle`, or `no_cycle_observed`. |
| `scope` | Always `inspected_manifests`. |
| `cycle` | One closed path in depends-on order, or an empty list. It is not a list of every cycle. |
| `node_count`, `edge_count` | Inspected manifests and distinct resolved edges included in the analysis. |
| `uninspected_modules` | Inventory modules whose dependency declarations were not inspected, because of selection or manifest errors. |
| `excluded_edge_counts` | Declaration counts by `missing`, `unknown`, `invalid`, and `uninspected_target`. |

Counts and uninspected-module names appear after analysis. Early scan or output
limit failures leave `status=not_checked`; they do not claim graph inspection
completed. Per-module `dependencies_inspected` records whether literal manifest
parsing reached dependency inspection. Invalid individual declarations remain in
the findings and excluded counts. Valid declarations in the same manifest can
still establish a cycle.

`no_cycle_observed` means no cycle was found in this graph. It does not establish
that omitted modules, missing sources or the runtime installation are cycle-free.
Strict dependency checks keep their existing missing/unknown behavior. Existing
invalid-declaration, manifest, malformed-data and missing-dependency failures take
precedence over `DEPENDENCY_CYCLE`, while retaining cycle evidence. A confirmed
cycle takes precedence over blocked data inspection or incomplete inventory.

The existing inventory and findings-size limits bound graph size. Analysis uses
Python's [standard graph library](https://docs.python.org/3.12/library/graphlib.html)
and checks cancellation before and after cycle detection. The chosen witness is
repeatable for the same inputs and Python runtime but is not a stable identifier
across Python versions. Long cycles remain complete in evidence; human output
contains a bounded preview. There is no transitive solver or installation-order
promise. Odoo's pinned [module graph](https://github.com/odoo/odoo/blob/005e0a0eb7ef80cd15b0c82b570b2b0843181ba2/odoo/modules/module_graph.py)
skips modules in dependency loops, but static validation does not establish
runtime compatibility.
