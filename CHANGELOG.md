# Changelog

## 0.2.1
- Fix `run TARGET --timeout N -- cmd`: the timeout was ignored and sent to the instance as part of the command
- `list` no longer caches a Name tag shared by several instances, so `connect`/`run` still report the ambiguity
- `resolve`/`forward` reject invalid RDS/ElastiCache identifiers with a clear message
- Unknown `--profile` and other credential errors print a short error instead of a traceback
- Cache file is created with mode `600` from the start (no brief world-readable window)
- `docs/iam.md`: `ssm:SendCommand` is limited to `AWS-RunShellScript`

## 0.2.0
- Lookup cache for Name-tag and endpoint resolution (`--no-cache`, `--cache-ttl`, `SSMX_CACHE_TTL`, `ssmx cache clear`)
- `list` shows private IP and supports `-o json`; `resolve` supports `--ec2` and `-o json`
- `run` propagates the remote exit code and has a `--timeout`
- `param put` reads the value from stdin with `-`; `param delete` asks for confirmation
- ElastiCache cluster-mode (configuration endpoint) support
- Clearer errors for expired SSO sessions and missing regions

## 0.1.0
- Initial version: `list`, `connect`, `run`, `forward` with RDS / Aurora / ElastiCache name lookup, `resolve`, `param`
