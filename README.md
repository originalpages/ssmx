# ssmx

**A smarter AWS SSM CLI.** Shell access, one-off commands and port forwarding over
AWS Systems Manager — using *names* instead of instance IDs, endpoints and ports.

```bash
ssmx forward bastion-1 --to prod-db
# prod-db (rds:postgres) -> prod-db.abc123.eu-west-1.rds.amazonaws.com:5432
# forwarding localhost:5432 via bastion-1 (i-0abc1234def5678ab) - Ctrl+C to stop
```

You give it the RDS identifier. It looks up the endpoint and port for you, picks a
sensible local port, and opens the tunnel. No bastion SSH keys, no open ports, no
copy-pasting endpoints from the console.

---

## Why

The plain AWS CLI version of the command above is:

```bash
aws rds describe-db-instances --db-instance-identifier prod-db \
  --query 'DBInstances[0].Endpoint'            # find host + port
aws ec2 describe-instances --filters Name=tag:Name,Values=bastion-1 \
  --query 'Reservations[].Instances[].InstanceId'   # find instance ID
aws ssm start-session --target i-0abc1234def5678ab \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["prod-db.abc123.eu-west-1.rds.amazonaws.com"],"portNumber":["5432"],"localPortNumber":["5432"]}'
```

`ssmx` does all three steps in one command, and caches the lookups so repeat
calls are instant.

| Task | AWS CLI | ssmx |
|---|---|---|
| Shell on an instance | `aws ssm start-session --target i-0abc...` | `ssmx connect web-1` |
| Run a command | `aws ssm send-command ... --parameters commands=[...]` + poll for output | `ssmx run web-1 -- uptime` |
| Tunnel to RDS / Aurora / Redis | three commands, see above | `ssmx forward web-1 --to prod-db` |
| Instance by Name tag | manual `describe-instances` | built in |
| Read a SecureString | `aws ssm get-parameter --with-decryption --query ...` | `ssmx param get /app/DB_PASS` |

`ssmx` uses the same AWS APIs and the same IAM permissions as the AWS CLI. It is a
nicer interface, not a different security model.

---

## Install

**Prerequisites**

- Python 3.9+
- [AWS CLI v2](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html) (needed for `connect` and `forward`)
- Target instances must be SSM-managed (SSM Agent running + an instance profile with `AmazonSSMManagedInstanceCore`)

**Recommended: pipx** (isolated install, `ssmx` on your PATH)

```bash
pipx install git+https://github.com/originalpages/ssmx.git
```

**Or pip**

```bash
pip install git+https://github.com/originalpages/ssmx.git
```

**Or just the script** — it's a single file:

```bash
pip install boto3
curl -L https://raw.githubusercontent.com/originalpages/ssmx/main/ssmx.py -o ~/.local/bin/ssmx
chmod +x ~/.local/bin/ssmx
```

Check it works:

```bash
ssmx --version
ssmx list
```

---

## Usage

### Find instances

```bash
ssmx list                  # all running, SSM-managed instances
ssmx ls -f api             # filter by Name tag or ID substring
ssmx list -o json | jq     # machine-readable
```

```
NAME         INSTANCE ID           TYPE          PRIVATE IP       PING
api-1        i-0abc1234def5678ab   t3.medium     10.0.1.12        Online
bastion-1    i-0fed9876cba54321f   t3.micro      10.0.0.5         Online
```

### Open a shell

```bash
ssmx connect api-1                      # by Name tag
ssmx c i-0abc1234def5678ab              # or by instance ID
```

### Run a one-off command

```bash
ssmx run api-1 -- systemctl status nginx
ssmx run api-1 -- tail -n 100 /var/log/app.log
ssmx run api-1 --timeout 600 -- ./long-job.sh
```

stdout and stderr come back to your terminal, and the remote exit code becomes
`ssmx`'s exit code, so it works in scripts and `&&` chains.

### Port forward — the smart part

`--to` accepts any of these, tried in this order:

1. `host:port` — used as-is (anything TCP: OpenSearch, Kafka, an internal ALB…)
2. An **RDS instance** identifier
3. An **Aurora / RDS cluster** identifier (writer endpoint)
4. An **ElastiCache replication group** (primary endpoint, or configuration endpoint in cluster mode)
5. An **ElastiCache cache cluster** (Redis, Valkey or Memcached)

```bash
ssmx forward bastion-1 --to prod-db                 # RDS: finds host + port
ssmx fwd bastion-1 --to orders-aurora               # Aurora cluster
ssmx fwd bastion-1 --to sessions-redis              # ElastiCache
ssmx fwd bastion-1 --to prod-db --local 15432       # pick your own local port
ssmx fwd bastion-1 --to search.internal:9200        # explicit host:port
```

The local port defaults to the remote port. In another terminal:

```bash
psql -h localhost -p 5432 -U admin mydb
redis-cli -p 6379
```

> **Tip:** use `--local` when you already run the same database locally, e.g.
> `--local 15432` next to a local Postgres on 5432.

### Check what a name resolves to

Useful before connecting, or in scripts:

```bash
ssmx resolve prod-db
# prod-db (rds:postgres) -> prod-db.abc123.eu-west-1.rds.amazonaws.com:5432

ssmx resolve api-1 --ec2
# api-1 -> i-0abc1234def5678ab

ssmx resolve prod-db -o json
```

### Parameter Store

```bash
ssmx param get /myapp/prod/DB_PASSWORD                   # decrypts SecureString
export DB_PASS=$(ssmx param get /myapp/prod/DB_PASSWORD)

ssmx param list /myapp/prod/

ssmx param put /myapp/prod/API_URL https://api.example.com --type String
ssmx param put /myapp/prod/DB_PASSWORD - --overwrite < secret.txt   # '-' = read stdin
ssmx param delete /myapp/prod/OLD_KEY                    # asks for confirmation; -y to skip
```

`param put` defaults to `SecureString`. Prefer the `-` (stdin) form for secrets
so the value doesn't end up in your shell history.

---

## Profiles and regions

`ssmx` uses the standard AWS credential chain via boto3, and passes the same
profile and region to the `aws` CLI when it opens a session.

```bash
ssmx --profile prod connect api-1
ssmx --region us-east-1 list
AWS_PROFILE=staging ssmx fwd bastion-1 --to staging-db

# IAM Identity Center / SSO
aws sso login --profile prod
ssmx --profile prod list
```

Global options (`--profile`, `--region`, `--no-cache`, `--cache-ttl`) go
**before** the command.

---

## Lookup cache

Resolving names costs one or more AWS API calls. `ssmx` caches successful
lookups so repeat commands start instantly.

- **What is cached:** Name tag → instance ID, and resource name → host/port.
  **Never** credentials, parameter values or command output.
- **Where:** `~/.cache/ssmx/cache.json` (respects `XDG_CACHE_HOME`), file mode `600`.
- **Scope:** per profile + region, so prod and dev never mix.
- **Lifetime:** 5 minutes by default. `ssmx list` also warms the cache.

```bash
ssmx --no-cache connect api-1        # bypass once
ssmx --cache-ttl 3600 fwd b-1 --to db  # longer TTL for this call
export SSMX_CACHE_TTL=0              # disable entirely
ssmx cache clear                     # wipe it
ssmx cache path                      # show location
```

If an instance was replaced and a cached ID is stale, the session fails fast;
run `ssmx cache clear` (or wait for the TTL) and retry.

---

## IAM permissions

Minimum permissions for the caller, per command:

| Command | Actions |
|---|---|
| `list` | `ec2:DescribeInstances`, `ssm:DescribeInstanceInformation` |
| `connect` | `ec2:DescribeInstances`, `ssm:StartSession`, `ssm:TerminateSession` |
| `run` | `ec2:DescribeInstances`, `ssm:SendCommand`, `ssm:GetCommandInvocation` |
| `forward` | `connect` permissions + `rds:DescribeDBInstances`, `rds:DescribeDBClusters`, `elasticache:DescribeReplicationGroups`, `elasticache:DescribeCacheClusters` |
| `param get` | `ssm:GetParameter` (+ `kms:Decrypt` for SecureString with a customer key) |
| `param put` | `ssm:PutParameter` (+ `kms:Encrypt`) |
| `param list` | `ssm:DescribeParameters` |
| `param delete` | `ssm:DeleteParameter` |

`forward` also needs `ssm:StartSession` on the document
`arn:aws:ssm:*::document/AWS-StartPortForwardingSessionToRemoteHost`.
See [docs/iam.md](docs/iam.md) for a copy-paste policy.

The *network* path matters too: the tunnel instance's security group must be
allowed into the database's security group on the database port.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `no AWS region configured` | Pass `--region`, set `AWS_REGION`, or add `region` to your profile |
| `...token... expired` / SSO errors | `aws sso login --profile <name>` |
| `SessionManagerPlugin is not found` | Install the Session Manager plugin (see Prerequisites) |
| Instance not in `ssmx list` | It's not SSM-managed: check SSM Agent and the instance profile |
| `matches several running instances` | Two instances share a Name tag — use the instance ID |
| Tunnel opens but DB times out | Security group of the DB doesn't allow the tunnel instance |
| `Address already in use` | Something already listens on that port — use `--local <other port>` |
| Connects to an old/terminated instance | `ssmx cache clear` |

---

## Development

```bash
git clone https://github.com/originalpages/ssmx.git
cd ssmx
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

The whole tool is one file, `ssmx.py`. Pull requests welcome — please add a
test in `tests/` for new behaviour.

## License

[MIT](LICENSE)
