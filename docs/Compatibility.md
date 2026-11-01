# Compatibility, licensing and publication readiness

The owner selected the `mccann-hub-devkit` distribution family, the native
`mccann_hub` Python namespace and GPL-3.0-or-later on November 1, 2026. Registry
publication and release ownership are separate approvals; no names have been
reserved or packages published by this migration.

## Public extension points

| Interface | Compatibility commitment |
| --- | --- |
| `mccann_hub.devkit.contracts`, specialization API `1.0` | Existing fields and meanings stay compatible within the contract. Additive fields need defaults; incompatible contract changes require a new API version. |
| `mccann_hub.devkit.specializations.v1` entry-point group | Metadata discovery does not import plugins. Selected code loads only after operator trust checks. |
| `mccann_hub.devkit.app.create_service(project, timeout=None)` and returned `.execute(command, arguments, cancellation=...)` | Supported Python invocation entry point. Use keywords for optional behavior, not internal service/settings/policy constructors. |
| `mccann_hub.devkit.processes.run_process` and documented `RunStore` methods | Supported helpers tied to the foundation distribution version. |
| Result/evidence envelope `1.0` and reference metadata | Existing meanings remain; consumers tolerate additive fields. Historical evidence is readable without its producing plugin. |
| CLI and optional MCP | Shared command validation, authorization and results; IDs, timestamps and surface metadata differ per invocation. Automate against JSON and reason codes, not error prose. |

Private names, registration internals, configuration loaders and service attributes
are not extension contracts. Tests using public interfaces do not certify arbitrary
plugin code as safe. No testing SDK is needed.

### Optional Claude Code bundle

The [native plugin](../integrations/claude-code) is a separately maintained directory
bundle, version 0.1.0. It consumes foundation 0.2.0 with API/evidence 1.0 and requires
no Python package or import changes. Native loading, disablement, removal and local
MCP configuration were exercised with Claude Code 2.1.316 on Linux. Model-driven
qualification remains open because the test account reported insufficient credit.
This is not a compatibility promise for other Claude versions or other harnesses.
The CLI path remains independent of Claude and of the optional MCP adapter.

## Migration from the unpublished devkit distributions

Foundation 0.2.0 intentionally changes distribution/import names before public
release. The declaration and evidence contracts remain 1.0. This supersedes the
old 0.1.x Python import path; no top-level `devkit` compatibility shim is supplied
because it would retain the collision with an unrelated package.

| Previous distribution / import | Replacement distribution / import |
| --- | --- |
| `devkit` / `devkit` | `mccann-hub-devkit` / `mccann_hub.devkit` |
| `devkit-go` / `devkit_go` | `mccann-hub-devkit-go` / `mccann_hub.devkit_go` |
| `devkit-odoo` / `devkit_odoo` | `mccann-hub-devkit-odoo` / `mccann_hub.devkit_odoo` |
| `devkit-beads` / `devkit_beads` | `mccann-hub-devkit-beads` / `mccann_hub.devkit_beads` |
| `devkit-mcp` / `devkit_mcp` | `mccann-hub-devkit-mcp` / `mccann_hub.devkit_mcp` |
| `devkit-example` / `devkit_example` | `mccann-hub-devkit-example` / `mccann_hub.devkit_example` |

1. Create a fresh virtual environment and install reviewed renamed wheels together.
   Old and new Devkit environments can coexist separately. They expose the same
   `devkit` and `devkit-mcp` executable names, so do not install both generations
   into one environment. An unrelated top-level `devkit` import is not used by the
   new foundation; unrelated packages with colliding executable names still need
   separate environments.
2. Rebuild external plugins with `mccann-hub-devkit>=0.2,<0.3`, the new imports and
   entry-point group. Old `devkit.specializations.v1` registrations are ignored.
   Plugin authors should choose their own distribution/import namespace; the McCann
   Hub prefix is for this package family. The native `mccann_hub` root must have no
   `__init__.py`, allowing independently installed siblings.
3. Review each new artifact. Explicitly update distribution keys under
   `[trusted_plugins]`, wheel filenames and SHA-256 pins in the external policy.
   A grant trusting `devkit-go` does not trust `mccann-hub-devkit-go`. Trust is never
   copied automatically, even where plugin versions are unchanged.
4. Retain command grants, plugin selection IDs (`go`, `odoo`, `beads`), check
   profiles, `devkit.toml`, XDG `devkit` directories and `DEVKIT_*` environment
   variables. Command IDs and CLI syntax are unchanged. Do not rewrite evidence
   or references: existing run identities and stored distribution provenance remain
   historical facts. Retrieval and retention use the existing schemas.
5. Run `plugins list --details`, `plugins validate` and a verification profile.
   Check `runs show` and `runs list --reference` against pre-migration runs. Roll
   back by using the previous environment and its separately retained operator
   configuration; this migration requires no destructive evidence conversion.

Within the new 0.2.x line, preserve documented calls and fields. Document any future
incompatible change, affected versions and replacement before removal; prefer one
compatible migration release. Security exceptions must be explicit. A contract 2.0
requires separate registration tests. Distribution versions do not automatically
change the specialization API version.

## Licensing and provenance

Devkit, its bundled specializations and the copyable template are licensed under
**GPL-3.0-or-later**: GNU GPL version 3, or at the recipient's option any later
version published by the Free Software Foundation. See [LICENSE](../LICENSE).
Each distribution ships the GPLv3 text and an SPDX `License-Expression` plus
`License-File` metadata. The template can be copied and adapted under those terms;
retain its license and applicable notices when distributing derivatives.

Running Devkit on a project does not by itself change that project's license.
Private use does not generally require publication. Plugins importing core
contracts and exchanging objects need a licensing assessment as a combined
program when distributed; separate wheels alone do not establish legal separation.
Under the FSF's interpretation, such plugins need GPL-compatible licensing and
GPL-compliant distribution. A permissive template license alone would not remove
foundation integration obligations. See the [GNU plugin FAQ](https://www.gnu.org/licenses/gpl-faq.en.html#GPLAndPlugins).

Repository records describe a fresh implementation and synthetic Odoo fixtures,
not vendored Odoo/OCA or Beads implementations. Git history and inspection cannot
establish legal title by themselves; the owner authorizes this project's license.
Third-party dependencies retain their own licenses. Release review must preserve
applicable notices and review the exact dependency artifacts being distributed.
The synthetic CI addon uses the matching GPL-3 manifest category.

## Python, dependencies and release qualification

The qualified baseline is Linux with CPython 3.12. Metadata `Requires-Python >=3.12`
allows newer versions but does not certify them. The process supervisor, evidence
locking and template file checks use Linux facilities. No AI harness, Docker,
Beads or Odoo is required by the foundation.

Runtime ranges are in each `pyproject.toml`; `uv.lock` fixes acceptance versions.
Installed type-consumer tests verify the public annotations. Lower-bound dependency
and newer-Python matrices remain future qualification work. No new runtime
requirements were introduced by naming or licensing.

The selected family follows existing `mccann-hub-*` distributions and
`mccann_hub.*` imports. This is not an npm-style account scope or an ownership
reservation. PyPI's unrelated `devkit` project remains independent. Before a
release, approve registry ownership, exact name availability, protected release
workflow, artifact hashes and attestations. Prefer trusted publishing to stored
long-lived tokens. No publication workflow is enabled here.

## Trust limits

Installation, selection, trust and command grants remain separate. Version trust
is metadata, not executable identity. Optional wheel pins verify archive SHA-256
and installed payload before activation; they do not attest transitive dependencies
or sandbox Python code. `plugins list --details` reports configured trust without
verifying pins; `plugins validate` attempts activation and prerequisites. Build
unknown code in host isolation. Installation never grants permissions.
