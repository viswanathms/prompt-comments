# Project rules

<!-- Edit this file, then run `prompt-comments build`. CLAUDE.md is generated. -->

## Testing
Run `pytest -q` before committing.
<!-- why: the CI image has no tox; keep it to plain pytest -->

## Style
- Prefer small functions.
- Type-annotate public APIs.
// TODO(vishwa): decide on ruff vs black, then document it here

## Commands
```bash
make test   # fast: unit tests only
make e2e    # slow: needs docker
```
{# the comments inside the fence above are kept - code is never stripped #}
