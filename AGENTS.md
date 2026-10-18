# Repository policy

## Conventional Commits

Use [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)
for commit messages. This repository requires a scope:

```text
<type>(<scope>): <description>
```

- Use lowercase types and scopes. Choose a type that describes the change:
  `feat`, `fix`, `refactor`, `perf`, `docs`, `build`, `ci`, `test`, `chore` or `revert`.
- Scope service changes by service name, such as `forgejo`, `argus` or `backrest`.
  Scope shared work by task, such as `bootstrap`, `hardening`, `secrets` or `deploy`.
- Write a concise, imperative description of the resulting change.
- Group each commit by one area of concern. Include its related configuration,
  packages and documentation; separate unrelated services or tasks.
- Mark breaking changes with `!` before the colon or a `BREAKING CHANGE:` footer.
  Use an optional body to explain motivation and material operational implications.

Examples:

```text
feat(backrest): manage backups with Nix
fix(forgejo): provide Bash for Git hooks
refactor(hardening): share systemd isolation options
ci(forgejo): bound the persistent Nix cache
docs(bootstrap): explain Ubuntu prerequisites
```
