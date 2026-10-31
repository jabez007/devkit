# Synthetic Odoo repositories

These fixtures model project layouts and manifest relationships. They contain no
upstream Odoo/OCA code and are not installable applications. Even `base` and
`auditlog` are small synthetic stand-ins. Addon `__init__.py` files raise if
imported; the expression fixture must never write its marker.

`cases.json` defines the expected status, reason and relationship counts in
resolved/missing/unknown/invalid order. The same CLI acceptance script runs
against the development environment and an independently installed Odoo-only
wheel environment:

```sh
.venv/bin/python scripts/check_odoo_fixtures.py .venv/bin/devkit
```

Each case copies its repository into a temporary workspace and creates an
external, private operator policy. Checks exercise JSON and human CLI output,
persisted evidence and `runs show`. All fixture invocations remain offline.

| Repository | Purpose |
| --- | --- |
| standalone | Custom addon with unavailable standard `base` and `sale` dependencies. |
| internal | Custom modules with an internal edge and a complete `acme_` namespace. |
| oca | Separate custom and external addon paths, including a resolved OCA-style edge. |
| complete | Explicit full inventory with a genuinely absent custom dependency. |
| duplicates | Same module name in two configured paths; neither silently wins. |
| invalid_manifest | Executable expression rejected by literal parsing. |
| unsafe_path | Declared data path traverses outside its addon. |
| malformed_dependencies | Paths, dotted names and nonstrings are invalid declarations. |
| optional | Auto-install bridge plus unresolved module, Python and binary dependencies. |
| xml_valid | Ordered records, repeated IDs, template inheritance and demo references. |
| xml_ordering | Forward, external and demo-only references remain unknown. |
| xml_malformed | Syntax failure with a file and source location. |
| xml_dtd | DTD inspection blocks without fetching the external resource. |
| xml_dynamic | CSV interrupts reference certainty; Python expressions are never executed. |

The corpus now has fourteen layouts and twenty CLI scenarios.

Additional cases use arguments to select one module, require certainty, request
an unsafe addons path, or assert completeness over an unavailable path. Python
regressions separately cover scan/output limits, cancellation, symlinks and
malformed manifests. MCP tests compare results with both Python and CLI calls.
