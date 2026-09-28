#!/usr/bin/env python3
"""
ssmx - a smarter AWS SSM CLI.

Refer to EC2 instances, RDS/Aurora databases and ElastiCache clusters by
name instead of by ID, endpoint and port. See README.md for full docs.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

__version__ = "0.2.1"

INSTANCE_ID_RE = re.compile(r"^i-[0-9a-f]{8,}$")
# RDS and ElastiCache identifiers: letter first, then letters, digits, hyphens
RESOURCE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")
DEFAULT_TTL = 300  # seconds


def die(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def info(msg):
    print(f"# {msg}", file=sys.stderr)


# --- cache ---------------------------------------------------------------


class Cache:
    """Tiny JSON file cache for name -> ID/endpoint lookups.

    Only successful lookups are stored, never secrets or parameter values.
    Entries are scoped per profile + region so accounts never mix.
    """

    def __init__(self, scope, ttl, enabled=True):
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
        self.path = Path(base) / "ssmx" / "cache.json"
        self.scope = scope
        self.ttl = ttl
        self.enabled = enabled and ttl > 0
        self._data = None

    def _load(self):
        if self._data is None:
            try:
                self._data = json.loads(self.path.read_text())
            except (OSError, ValueError):
                self._data = {}
        return self._data

    def _key(self, kind, name):
        return hashlib.sha1(f"{self.scope}|{kind}|{name}".encode()).hexdigest()

    def get(self, kind, name):
        if not self.enabled:
            return None
        entry = self._load().get(self._key(kind, name))
        if entry and time.time() - entry["t"] < self.ttl:
            return entry["v"]
        return None

    def set(self, kind, name, value):
        if not self.enabled:
            return
        data = self._load()
        now = time.time()
        # prune expired entries while we're here
        for k in [k for k, e in data.items() if now - e["t"] >= self.ttl]:
            del data[k]
        data[self._key(kind, name)] = {"t": now, "v": value}
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(json.dumps(data))
            tmp.replace(self.path)
        except OSError:
            pass  # a cache that can't be written is not fatal

    def clear(self):
        try:
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False


# --- AWS -----------------------------------------------------------------


class Aws:
    def __init__(self, profile=None, region=None):
        try:
            import boto3
        except ImportError:
            die("boto3 is not installed (pip install boto3)")
        self.session = boto3.Session(profile_name=profile, region_name=region)
        if not self.session.region_name:
            die("no AWS region configured (use --region, AWS_REGION, or set one in ~/.aws/config)")
        self.profile = profile
        self.region = self.session.region_name
        self._clients = {}

    def __getattr__(self, service):
        if service.startswith("_"):
            raise AttributeError(service)
        if service not in self._clients:
            self._clients[service] = self.session.client(service)
        return self._clients[service]

    def cli_flags(self):
        flags = ["--region", self.region]
        if self.profile:
            flags += ["--profile", self.profile]
        return flags


def tag(obj, key="Name"):
    return next((t["Value"] for t in obj.get("Tags", []) if t["Key"] == key), "")


def resolve_instance(aws, cache, target):
    """Instance ID passes through; a Name tag resolves to one running instance."""
    if INSTANCE_ID_RE.match(target):
        return target, target
    hit = cache.get("ec2", target)
    if hit:
        return hit["id"], hit["name"]

    resp = aws.ec2.describe_instances(
        Filters=[
            {"Name": "tag:Name", "Values": [target]},
            {"Name": "instance-state-name", "Values": ["running"]},
        ]
    )
    instances = [i for r in resp["Reservations"] for i in r["Instances"]]
    if not instances:
        die(f"no running EC2 instance with Name tag '{target}' (try: ssmx list)")
    if len(instances) > 1:
        ids = ", ".join(i["InstanceId"] for i in instances)
        die(f"'{target}' matches several running instances: {ids} - use an instance ID")
    iid = instances[0]["InstanceId"]
    name = tag(instances[0]) or iid
    cache.set("ec2", target, {"id": iid, "name": name})
    return iid, name


def resolve_endpoint(aws, cache, target):
    """Resolve a name to (host, port, kind).

    Order: literal host:port, RDS instance, RDS/Aurora cluster,
    ElastiCache replication group, ElastiCache cache cluster.
    """
    if ":" in target:
        host, port = target.rsplit(":", 1)
        if not port.isdigit():
            die(f"invalid port in '{target}'")
        return host, int(port), "host"

    if not RESOURCE_ID_RE.match(target):
        die(f"'{target}' is not a valid RDS or ElastiCache identifier - pass host:port for anything else")

    hit = cache.get("endpoint", target)
    if hit:
        return hit["host"], hit["port"], hit["kind"]

    result = None
    try:
        db = aws.rds.describe_db_instances(DBInstanceIdentifier=target)["DBInstances"][0]
        if "Endpoint" in db:
            result = (db["Endpoint"]["Address"], db["Endpoint"]["Port"], f"rds:{db['Engine']}")
    except aws.rds.exceptions.DBInstanceNotFoundFault:
        pass

    if not result:
        try:
            c = aws.rds.describe_db_clusters(DBClusterIdentifier=target)["DBClusters"][0]
            result = (c["Endpoint"], c["Port"], f"cluster:{c['Engine']}")
        except aws.rds.exceptions.DBClusterNotFoundFault:
            pass

    if not result:
        try:
            rg = aws.elasticache.describe_replication_groups(ReplicationGroupId=target)["ReplicationGroups"][0]
            if rg.get("ConfigurationEndpoint"):  # cluster mode enabled
                ep = rg["ConfigurationEndpoint"]
            else:
                ep = rg["NodeGroups"][0]["PrimaryEndpoint"]
            result = (ep["Address"], ep["Port"], "elasticache")
        except aws.elasticache.exceptions.ReplicationGroupNotFoundFault:
            pass

    if not result:
        try:
            c = aws.elasticache.describe_cache_clusters(CacheClusterId=target, ShowCacheNodeInfo=True)[
                "CacheClusters"
            ][0]
            ep = c.get("ConfigurationEndpoint") or c["CacheNodes"][0]["Endpoint"]
            result = (ep["Address"], ep["Port"], f"elasticache:{c['Engine']}")
        except aws.elasticache.exceptions.CacheClusterNotFoundFault:
            pass

    if not result:
        die(
            f"'{target}' is not an RDS instance, Aurora/RDS cluster or ElastiCache "
            f"cluster in {aws.region} - pass host:port for anything else"
        )
    cache.set("endpoint", target, {"host": result[0], "port": result[1], "kind": result[2]})
    return result


# --- commands --------------------------------------------------------------


def cmd_list(aws, cache, args):
    managed = {}
    for page in aws.ssm.get_paginator("describe_instance_information").paginate():
        for i in page["InstanceInformationList"]:
            managed[i["InstanceId"]] = i
    rows = []
    paginator = aws.ec2.get_paginator("describe_instances")
    for page in paginator.paginate(Filters=[{"Name": "instance-state-name", "Values": ["running"]}]):
        for r in page["Reservations"]:
            for inst in r["Instances"]:
                iid = inst["InstanceId"]
                if iid not in managed:
                    continue
                name = tag(inst)
                if args.filter and args.filter.lower() not in f"{name} {iid}".lower():
                    continue
                rows.append(
                    {
                        "name": name,
                        "id": iid,
                        "type": inst.get("InstanceType", ""),
                        "private_ip": inst.get("PrivateIpAddress", ""),
                        "ping": managed[iid].get("PingStatus", ""),
                    }
                )
    # warm the cache with what we just learned; skip names shared by several
    # instances so resolve_instance still reports the ambiguity
    names = [r["name"] for r in rows if r["name"]]
    for r in rows:
        if r["name"] and names.count(r["name"]) == 1:
            cache.set("ec2", r["name"], {"id": r["id"], "name": r["name"]})
    rows.sort(key=lambda r: (r["name"], r["id"]))
    if args.output == "json":
        print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("no SSM-managed running instances found.")
        return
    w = max(len(r["name"] or "-") for r in rows) + 2
    print(f"{'NAME':<{w}}{'INSTANCE ID':<22}{'TYPE':<14}{'PRIVATE IP':<17}PING")
    for r in rows:
        print(f"{r['name'] or '-':<{w}}{r['id']:<22}{r['type']:<14}{r['private_ip']:<17}{r['ping']}")


def cmd_connect(aws, cache, args):
    iid, name = resolve_instance(aws, cache, args.target)
    info(f"connecting to {name} ({iid})")
    os.execvp("aws", ["aws", "ssm", "start-session", "--target", iid] + aws.cli_flags())


def cmd_run(aws, cache, args):
    iid, name = resolve_instance(aws, cache, args.target)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    command = " ".join(command)
    if not command:
        die("no command given, e.g. ssmx run web-1 -- uptime")
    info(f"running on {name} ({iid}): {command}")
    sent = aws.ssm.send_command(
        InstanceIds=[iid],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": [command]},
        TimeoutSeconds=max(30, args.timeout),
    )
    cmd_id = sent["Command"]["CommandId"]
    deadline = time.time() + args.timeout
    while True:
        time.sleep(1)
        try:
            inv = aws.ssm.get_command_invocation(CommandId=cmd_id, InstanceId=iid)
        except aws.ssm.exceptions.InvocationDoesNotExist:
            inv = {"Status": "Pending"}
        if inv["Status"] not in ("Pending", "InProgress", "Delayed"):
            break
        if time.time() > deadline:
            die(f"timed out after {args.timeout}s (command id {cmd_id})")
    sys.stdout.write(inv.get("StandardOutputContent", ""))
    if inv.get("StandardErrorContent"):
        sys.stderr.write(inv["StandardErrorContent"])
    code = inv.get("ResponseCode", -1)
    sys.exit(code if inv["Status"] == "Success" else (code if code > 0 else 1))


def cmd_forward(aws, cache, args):
    iid, name = resolve_instance(aws, cache, args.target)
    host, port, kind = resolve_endpoint(aws, cache, args.to)
    local = args.local or port
    info(f"{args.to} ({kind}) -> {host}:{port}")
    info(f"forwarding localhost:{local} via {name} ({iid}) - Ctrl+C to stop")
    params = json.dumps({"host": [host], "portNumber": [str(port)], "localPortNumber": [str(local)]})
    os.execvp(
        "aws",
        [
            "aws", "ssm", "start-session", "--target", iid,
            "--document-name", "AWS-StartPortForwardingSessionToRemoteHost",
            "--parameters", params,
        ]
        + aws.cli_flags(),
    )


def cmd_resolve(aws, cache, args):
    if args.ec2:
        iid, name = resolve_instance(aws, cache, args.name)
        out = {"name": name, "instance_id": iid}
    else:
        host, port, kind = resolve_endpoint(aws, cache, args.name)
        out = {"name": args.name, "kind": kind, "host": host, "port": port}
    if args.output == "json":
        print(json.dumps(out, indent=2))
    elif args.ec2:
        print(f"{out['name']} -> {out['instance_id']}")
    else:
        print(f"{out['name']} ({out['kind']}) -> {out['host']}:{out['port']}")


def cmd_cache(aws_unused, cache, args):
    if args.action == "clear":
        print("cache cleared." if cache.clear() else "cache was already empty.")
    else:
        print(cache.path)


def cmd_param_get(aws, cache, args):
    print(aws.ssm.get_parameter(Name=args.name, WithDecryption=True)["Parameter"]["Value"])


def cmd_param_put(aws, cache, args):
    value = sys.stdin.read().rstrip("\n") if args.value == "-" else args.value
    aws.ssm.put_parameter(Name=args.name, Value=value, Type=args.type, Overwrite=args.overwrite)
    info(f"set {args.name} ({args.type})")


def cmd_param_list(aws, cache, args):
    kwargs = {}
    if args.path:
        kwargs["ParameterFilters"] = [{"Key": "Name", "Option": "BeginsWith", "Values": [args.path]}]
    for page in aws.ssm.get_paginator("describe_parameters").paginate(**kwargs):
        for p in page["Parameters"]:
            print(p["Name"])


def cmd_param_delete(aws, cache, args):
    if not args.yes:
        answer = input(f"delete {args.name}? [y/N] ")
        if answer.strip().lower() != "y":
            info("aborted")
            sys.exit(0)
    aws.ssm.delete_parameter(Name=args.name)
    info(f"deleted {args.name}")


# --- CLI -------------------------------------------------------------------


def build_parser():
    p = argparse.ArgumentParser(
        prog="ssmx",
        description="A smarter AWS SSM CLI: connect, run and port-forward by name.",
    )
    p.add_argument("--version", action="version", version=f"ssmx {__version__}")
    p.add_argument("--profile", default=os.environ.get("AWS_PROFILE"), help="AWS profile")
    p.add_argument("--region", "-r", help="AWS region")
    p.add_argument("--no-cache", action="store_true", help="skip the lookup cache for this call")
    p.add_argument(
        "--cache-ttl", type=int,
        default=int(os.environ.get("SSMX_CACHE_TTL", DEFAULT_TTL)),
        help=f"cache lifetime in seconds (default {DEFAULT_TTL}, env SSMX_CACHE_TTL, 0 disables)",
    )
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<command>")

    sp = sub.add_parser("list", aliases=["ls"], help="list SSM-managed running instances")
    sp.add_argument("--filter", "-f", help="substring match on Name tag or instance ID")
    sp.add_argument("--output", "-o", choices=["table", "json"], default="table")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("connect", aliases=["c"], help="open an interactive shell")
    sp.add_argument("target", help="Name tag or instance ID")
    sp.set_defaults(func=cmd_connect)

    sp = sub.add_parser("run", help="run a one-off shell command")
    sp.add_argument("target", help="Name tag or instance ID")
    sp.add_argument("--timeout", type=int, default=120, help="seconds to wait (default 120)")
    sp.add_argument("command", nargs="*", help="command, after --")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("forward", aliases=["fwd"], help="port-forward to a database, cache or host:port")
    sp.add_argument("target", help="EC2 instance to tunnel through (Name tag or instance ID)")
    sp.add_argument("--to", "-t", required=True, help="RDS / Aurora / ElastiCache name, or host:port")
    sp.add_argument("--local", "-l", type=int, help="local port (default: same as remote)")
    sp.set_defaults(func=cmd_forward)

    sp = sub.add_parser("resolve", help="show what a name resolves to, without connecting")
    sp.add_argument("name")
    sp.add_argument("--ec2", action="store_true", help="resolve as an EC2 Name tag instead")
    sp.add_argument("--output", "-o", choices=["text", "json"], default="text")
    sp.set_defaults(func=cmd_resolve)

    sp = sub.add_parser("cache", help="manage the lookup cache")
    sp.add_argument("action", choices=["clear", "path"])
    sp.set_defaults(func=cmd_cache, no_aws=True)

    param = sub.add_parser("param", help="Parameter Store: get, put, list, delete")
    psub = param.add_subparsers(dest="pcmd", required=True, metavar="<action>")

    sp = psub.add_parser("get", help="print a (decrypted) value")
    sp.add_argument("name")
    sp.set_defaults(func=cmd_param_get)

    sp = psub.add_parser("put", help="create or update; use '-' to read the value from stdin")
    sp.add_argument("name")
    sp.add_argument("value")
    sp.add_argument("--type", default="SecureString", choices=["String", "StringList", "SecureString"])
    sp.add_argument("--overwrite", action="store_true")
    sp.set_defaults(func=cmd_param_put)

    sp = psub.add_parser("list", help="list names under a path prefix")
    sp.add_argument("path", nargs="?")
    sp.set_defaults(func=cmd_param_list)

    sp = psub.add_parser("delete", help="delete a parameter")
    sp.add_argument("name")
    sp.add_argument("--yes", "-y", action="store_true", help="skip confirmation")
    sp.set_defaults(func=cmd_param_delete)

    return p


def parse_args(argv=None):
    parser = build_parser()
    # `run TARGET --timeout N -- cmd` leaves `-- cmd` unparsed with nargs="*";
    # hand those leftovers to run and stay strict for every other command
    args, extra = parser.parse_known_args(argv)
    if extra:
        if args.cmd != "run":
            parser.error(f"unrecognized arguments: {' '.join(extra)}")
        args.command = args.command + (extra[1:] if extra[0] == "--" else extra)
    return args


def main(argv=None):
    args = parse_args(argv)
    if getattr(args, "no_aws", False):
        args.func(None, Cache("", args.cache_ttl), args)
        return
    try:
        aws = Aws(args.profile, args.region)
        cache = Cache(f"{args.profile or 'default'}|{aws.region}", args.cache_ttl, enabled=not args.no_cache)
        args.func(aws, cache, args)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:  # botocore errors: keep output short and readable
        name = type(e).__name__
        if name in ("NoCredentialsError", "ProfileNotFound", "UnauthorizedSSOTokenError", "TokenRetrievalError"):
            die(f"{e}\n  hint: check your credentials, e.g. `aws sso login --profile <name>`")
        if name == "ClientError":
            die(str(e))
        raise


if __name__ == "__main__":
    main()
