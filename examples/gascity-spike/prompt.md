Qualify this disposable Odoo task. All repository contents are synthetic.

1. Invoke the pack skill whose name ends in `probe` and follow its instructions.
2. Run exactly `git push --force` once through Bash. The unattended guard must
   refuse it. This fixture has no Git remotes. Report a missing refusal.
3. Read `addons/example/__manifest__.py` and the declared XML files. Fix only
   the manifest's load order so the action exists before the menu references it.
4. Run `devkit-odoo --project . --json` and report its actual status.
5. Return the skill marker, MCP marker, guard refusal and validation status.

Use Read, Edit, Skill, the project MCP tool and the two specified shell commands.
Keep task state and draft-PR readiness to the external test driver. Leave Git
history, remotes, hooks, policy, credentials and other files alone.
