import stat
import time
import types

import pytest
import ssmx


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    return ssmx.Cache("default|eu-west-1", ttl=60)


def test_cache_roundtrip(cache):
    assert cache.get("ec2", "web-1") is None
    cache.set("ec2", "web-1", {"id": "i-0123456789abcdef0", "name": "web-1"})
    assert cache.get("ec2", "web-1")["id"] == "i-0123456789abcdef0"


def test_cache_expires(cache, monkeypatch):
    cache.set("endpoint", "db", {"host": "h", "port": 5432, "kind": "rds"})
    real = time.time
    monkeypatch.setattr(ssmx.time, "time", lambda: real() + 61)
    assert cache.get("endpoint", "db") is None


def test_cache_is_scoped_per_profile_and_region(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    ssmx.Cache("prod|eu-west-1", 60).set("ec2", "web-1", {"id": "i-aaaaaaaa", "name": "web-1"})
    assert ssmx.Cache("dev|eu-west-1", 60).get("ec2", "web-1") is None


def test_cache_disabled(cache):
    off = ssmx.Cache(cache.scope, ttl=0)
    off.set("ec2", "x", {"id": "i-12345678"})
    assert off.get("ec2", "x") is None


def test_host_port_passthrough_needs_no_aws(cache):
    assert ssmx.resolve_endpoint(None, cache, "db.internal:5432") == ("db.internal", 5432, "host")


def test_instance_id_passthrough_needs_no_aws(cache):
    assert ssmx.resolve_instance(None, cache, "i-0abc1234def5678ab") == ("i-0abc1234def5678ab", "i-0abc1234def5678ab")


def test_parser_run_keeps_command():
    args = ssmx.parse_args(["run", "web-1", "--", "df", "-h", "/"])
    assert args.command == ["df", "-h", "/"]


@pytest.mark.parametrize(
    "argv, timeout, command",
    [
        (["run", "api-1", "--timeout", "600", "--", "./long-job.sh"], 600, ["./long-job.sh"]),
        (["--profile", "x", "run", "w", "--timeout", "5", "--", "ls", "-la"], 5, ["ls", "-la"]),
        (["run", "w", "--", "ls", "--timeout", "3"], 120, ["ls", "--timeout", "3"]),
        (["run", "w", "uptime"], 120, ["uptime"]),
    ],
)
def test_parser_run_options_before_double_dash(argv, timeout, command):
    args = ssmx.parse_args(argv)
    assert (args.timeout, args.command) == (timeout, command)


def test_parser_rejects_extra_args_for_other_commands():
    with pytest.raises(SystemExit):
        ssmx.parse_args(["list", "--", "junk"])


def test_cache_file_is_private(cache):
    cache.set("ec2", "web-1", {"id": "i-0123456789abcdef0", "name": "web-1"})
    assert stat.S_IMODE(cache.path.stat().st_mode) == 0o600


def _fake_aws(instances):
    page = {"Reservations": [{"Instances": instances}]}
    info = {"InstanceInformationList": [{"InstanceId": i["InstanceId"]} for i in instances]}
    pager = lambda result: types.SimpleNamespace(paginate=lambda **kw: [result])  # noqa: E731
    return types.SimpleNamespace(
        ec2=types.SimpleNamespace(get_paginator=lambda _: pager(page), describe_instances=lambda **kw: page),
        ssm=types.SimpleNamespace(get_paginator=lambda _: pager(info)),
    )


def test_list_does_not_cache_duplicate_names(cache, capsys):
    named = lambda iid: {"InstanceId": iid, "Tags": [{"Key": "Name", "Value": "web"}]}  # noqa: E731
    aws = _fake_aws([named("i-aaaaaaaa1"), named("i-bbbbbbbb2")])
    ssmx.cmd_list(aws, cache, types.SimpleNamespace(filter=None, output="json"))
    assert cache.get("ec2", "web") is None
    with pytest.raises(SystemExit):
        ssmx.resolve_instance(aws, cache, "web")
    assert "several running instances" in capsys.readouterr().err


def test_invalid_identifier_needs_no_aws(cache, capsys):
    with pytest.raises(SystemExit):
        ssmx.resolve_endpoint(None, cache, "bad.name_x")
    assert "not a valid RDS or ElastiCache identifier" in capsys.readouterr().err


def test_unknown_profile_is_a_short_error(capsys):
    with pytest.raises(SystemExit):
        ssmx.main(["--profile", "ssmx-test-no-such-profile", "--region", "eu-west-1", "list"])
    assert "hint: check your credentials" in capsys.readouterr().err
