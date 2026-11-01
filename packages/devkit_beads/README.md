# Devkit Beads integration

Optional task lifecycle and evidence associations through Beads 1.3.2. Sequential linked worktrees are supported; concurrent writers remain unqualified.

Install reviewed local wheel artifacts alongside the Devkit foundation. Distribution
names are provisional; the public PyPI `devkit` project is unrelated. Installation
does not activate plugins, grant trust or write operator policy.

After selecting the required plugins in project configuration and explicitly
authorizing them in the external operator policy, use:

```sh
devkit --project /path/to/project run beads.workspace
```

See the [onboarding guide](https://github.com/jabez007/devkit/blob/main/docs/Getting_Started.md)
for developer and operator setup, and the
[plugin contract](https://github.com/jabez007/devkit/blob/main/docs/Plugin_Contract.md)
for extension authoring. The tested baseline is Linux and Python 3.12.

License selection and distribution ownership remain owner decisions. These
artifacts are not prepared for public redistribution until those decisions are
resolved. See the [compatibility policy](https://github.com/jabez007/devkit/blob/main/docs/Compatibility.md).
