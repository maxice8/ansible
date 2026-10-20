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

## Code style

Use ASD-STE100 for comments and docstrings. Use short sentences and stable terms.
Describe what the code does. Avoid labels such as "final configuration".
Format Nix files with the official `nixfmt` formatter.

## Package selection

Use Nixpkgs when it provides the application. Use `flake.lock` to select versions.
Do not add Nixpkgs version overrides to follow newer upstream releases.
Check the binary cache before starting a package build. Defer upgrades that need
an uncached source build when the application is available through Nixpkgs.
Use local packaging when Nixpkgs does not provide the application. Keep existing
pins when the Nixpkgs replacement needs an uncached source build.
Keep existing pins across a major-version gap. Minor and patch downgrades to
Nixpkgs are allowed. Check runtime compatibility before activation.
