# Native Odoo 19 test report

The runtime check loads this private addon through Odoo's native `--load`
option. Devkit's offline validator and plugin discovery do not import it.
It observes `odoo.tests.loader.run_suite` and the native result callbacks;
Odoo continues to select, execute and judge the tests.

The caller supplies a new absolute `DEVKIT_ODOO_REPORT` path in its private job
directory and a 32-character hexadecimal `DEVKIT_ODOO_JOB_TOKEN`. The report
uses protocol 1, carries that token, and remains `complete: false` until normal
interpreter shutdown. An unfinished suite or an early stop without a recorded
failure keeps it incomplete, even if Odoo exits zero. The consumer also checks
the process exit status.
Report replacements are atomic and use mode 0600.

The `tests` object contains:

- `collected`: cases counted in the native selected suites before execution.
- `run`: native starts excluding cases skipped after a start. Each callback is
  counted, including repeated test identities. Class setup skips do not subtract
  unrelated executed tests.
- `failed`: native failure and error outcomes, including setup failures and subtests.
- `skipped`: native skip events. A class setup skip is one event, so these
  counters do not always add up to the selected case count.

Each recorded failure has its native test identity and the last 4 KiB of its
traceback. At most 50 failure details are retained; `failures_omitted` counts
the remaining details. The native failure total remains complete. Disable
native failure retries in the calling runtime so attempt counts stay explicit.

The marked acceptance tests exercise the pinned Odoo 19 image against a private,
disposable PostgreSQL server. Run them from a Docker-capable shell:

```sh
DEVKIT_ODOO_RUNTIME=1 uv run pytest -m odoo_runtime tests/test_odoo_runtime_reporting.py
```

The integration follows the native
[loader](https://github.com/odoo/odoo/blob/19.0/odoo/tests/loader.py),
[suite](https://github.com/odoo/odoo/blob/19.0/odoo/tests/suite.py), and
[result](https://github.com/odoo/odoo/blob/19.0/odoo/tests/result.py) interfaces.
