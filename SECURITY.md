# Security Policy

## Supported versions

`ssmx` is a small, fast-moving CLI. Security fixes are released for the latest
minor version only.

| Version | Supported |
|---------|-----------|
| 0.2.x   | ✅        |
| < 0.2   | ❌        |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately through GitHub's
[private vulnerability reporting](https://github.com/originalpages/ssmx/security/advisories/new)
(repository → **Security** → **Report a vulnerability**).

Please include:

- A description of the issue and its impact
- Steps to reproduce, or a proof of concept
- The `ssmx` version (`ssmx --version`), Python version and OS
- Any suggested fix, if you have one

You can expect an acknowledgement within **7 days**. This is a volunteer-run
project, so fix timelines depend on severity, but we will keep you updated and
credit you in the release notes and advisory if you wish.

Please give us a reasonable chance to release a fix before disclosing publicly.

## Scope

`ssmx` is a thin wrapper around the AWS APIs and the AWS CLI. It uses the
caller's own AWS credentials and IAM permissions and adds no security model of
its own.

In scope:

- Command or argument injection (e.g. via instance names, tags, resource
  identifiers or parameter values passed to `aws`, `session-manager-plugin` or
  remote shells)
- Leaking secrets: credentials, Parameter Store values or command output in
  logs, error messages, process arguments or the lookup cache
- The lookup cache (`~/.cache/ssmx/cache.json`): unsafe file permissions, path
  handling, or cache poisoning that redirects a tunnel to an unintended host
- Packaging or CI issues that could compromise releases

Out of scope:

- Vulnerabilities in AWS services, the AWS CLI, boto3 or the Session Manager
  plugin (report those to AWS or the respective project)
- Over-broad IAM permissions in your own account; see
  [`docs/iam.md`](docs/iam.md) for least-privilege guidance
- Attacks that require an attacker to already control your machine or AWS
  credentials

## Safe use

- Grant only the IAM permissions you need ([`docs/iam.md`](docs/iam.md)).
- Never paste real credentials, parameter values or account IDs into issues or
  pull requests.
