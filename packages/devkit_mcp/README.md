# Devkit MCP adapter

Optional local stdio MCP presentation of the shared command service. Does not add authorization or orchestration.

Install reviewed local wheels from the `mccann-hub-devkit` package family.
The unrelated PyPI `devkit` project is not this foundation. Installation
does not activate plugins, grant trust or write operator policy.

After selecting the required plugins in project configuration and explicitly
authorizing them in the external operator policy, use:

```sh
devkit-mcp --project /path/to/project
```

See the [onboarding guide](https://github.com/jabez007/devkit/blob/main/docs/Getting_Started.md)
for developer and operator setup, and the
[plugin contract](https://github.com/jabez007/devkit/blob/main/docs/Plugin_Contract.md)
for extension authoring. The tested baseline is Linux and Python 3.12.

Licensed under GNU GPL version 3 or, at your option, any later version published
by the Free Software Foundation (`GPL-3.0-or-later`). See [LICENSE](LICENSE).
Registry publication and release ownership remain separate approvals; see the
[compatibility policy](https://github.com/jabez007/devkit/blob/main/docs/Compatibility.md).
