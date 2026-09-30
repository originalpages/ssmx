# Contributing to ssmx

Thanks for helping improve `ssmx`! Bug reports, ideas and pull requests are all
welcome.

By participating you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
For security issues, **do not** open a public issue; see [SECURITY.md](SECURITY.md).

## Reporting bugs

Search [existing issues](https://github.com/originalpages/ssmx/issues) first,
then open a new one with:

- What you ran and what you expected
- What happened (full error output; add `--no-cache` to rule out stale lookups)
- `ssmx --version`, Python version, AWS CLI version and OS
- The kind of target involved (EC2, RDS, Aurora, ElastiCache)

**Redact** account IDs, hostnames, instance IDs and anything secret.

## Suggesting features

Open an issue describing the problem you want to solve before writing a large
change, so we can agree on the approach. `ssmx` aims to stay small: a
single-file CLI that uses names instead of IDs and endpoints.

## Development setup

Requires Python 3.9+.

```bash
git clone https://github.com/originalpages/ssmx.git
cd ssmx
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Tests are mocked; they need no AWS account or credentials.

## Making a change

1. Fork the repo and create a branch from `main` (e.g. `fix/forward-port-clash`).
   Don't commit directly to `main`.
2. Keep the change focused; one logical change per pull request.
3. Add or update tests in `tests/test_ssmx.py` for new behaviour and bug fixes.
4. Run `pytest -q` and `ssmx --help` (both run in CI on Python 3.9 and 3.12).
5. Update `README.md` and `docs/iam.md` if you change commands, options or the
   IAM permissions a command needs.
6. Add a line to `CHANGELOG.md` for user-visible changes.

### Code guidelines

- The whole tool lives in `ssmx.py`; keep it that way unless there is a strong
  reason to split.
- Only dependency is `boto3`. Avoid adding new runtime dependencies.
- Stay compatible with Python 3.9.
- Never log or cache credentials, parameter values or command output.
- Launch `aws` with an argument list (`os.execvp`), never through a shell string.
- Prefer clear, short error messages over tracebacks for expected failures.

### Commit messages

Short imperative subject line (about 50 characters), with a body explaining
*why* when it isn't obvious, e.g. `Fix --timeout being sent to the instance`.

## Pull requests

- Open the PR against `main` and describe what changed and why; link any
  related issue (`Fixes #123`).
- CI must pass.
- Maintainers may ask for changes; please keep the discussion on the PR.

## License

By contributing you agree that your contributions are licensed under the
[MIT License](LICENSE).
