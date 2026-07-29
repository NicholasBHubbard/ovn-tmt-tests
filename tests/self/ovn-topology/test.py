import json
import os
import time

import pytest
from ovn_test.command import Runner
from ovn_test.config import read_int
from ovn_test.ovsdb import Ovsdb


MANAGED = "external_ids:ovn-tmt-tests-id="
OWNER = "external_ids:ovn-tmt-tests-owner="
SCOPE = "external_ids:ovn-tmt-tests-scope="


@pytest.fixture
def runner():
    return Runner()


@pytest.fixture
def nb(runner):
    return Ovsdb(runner, "ovn-nbctl")


@pytest.fixture
def sb(runner):
    return Ovsdb(runner, "ovn-sbctl")


def scale_rows(nb, table):
    return nb.find(table, f"{OWNER}self-scale", columns=("_uuid", "name"))


def scale_managed_rows(nb, table):
    return [
        row
        for row in nb.find(table, columns=("_uuid", "external_ids"))
        if row["external_ids"].get("ovn-tmt-tests-id", "").startswith("self-scale:")
    ]


def scale_gateway_rows(nb):
    return [
        row
        for row in nb.find("Gateway_Chassis", columns=("_uuid", "name"))
        if row["name"].startswith("self-scale:")
    ]


def assert_scale_counts(nb, workers):
    assert len(scale_rows(nb, "Logical_Switch")) == 1 + 2 * workers
    assert len(scale_rows(nb, "Logical_Router")) == 1 + workers
    assert len(scale_rows(nb, "Logical_Router_Port")) == 1 + 3 * workers
    assert len(scale_gateway_rows(nb)) == workers
    assert len(scale_managed_rows(nb, "NAT")) == 2 * workers
    assert (
        len(
            nb.find(
                "Logical_Router_Static_Route",
                f"{SCOPE}self-scale",
                columns=("_uuid",),
            )
        )
        == 6 * workers
    )


def assert_scale_group_attachments(nb, workers):
    group = nb.by_name(
        "Load_Balancer_Group",
        "cluster-lb-group1",
        "_uuid",
        "name",
    )
    assert group["name"] == "cluster-lb-group1"
    assert set(
        nb.referring_names("Logical_Switch", "load_balancer_group", group["_uuid"])
    ) == {f"lswitch-ovn-scale-{index}" for index in range(workers)}
    assert set(
        nb.referring_names("Logical_Router", "load_balancer_group", group["_uuid"])
    ) == {f"gwrouter-ovn-scale-{index}" for index in range(workers)}


def assert_scale_external_vlans(nb, workers):
    for index in {0, workers - 1}:
        port = nb.by_name(
            "Logical_Switch_Port",
            f"provnet-ovn-scale-{index}",
            "tag",
            "tag_request",
        )
        assert port["tag"] == index + 1
        assert port["tag_request"] == index + 1


def scale_southbound_names(workers):
    names = [f"ovn-scale-{index}" for index in range(workers)]
    datapaths = {"ls-join1", "lr-cluster1"}
    ports = {"ls-join1-to-rtr"}
    for name in names:
        datapaths.update(
            {
                f"lswitch-{name}",
                f"ext-{name}",
                f"gwrouter-{name}",
            }
        )
        ports.update(
            {
                f"node-to-rtr-{name}",
                f"join-to-gw-{name}",
                f"ext-to-gw-{name}",
                f"provnet-{name}",
            }
        )
    return datapaths, ports


def southbound_names(sb):
    datapaths = {
        external_ids.get("name")
        for external_ids in sb.values("Datapath_Binding", "external_ids")
    }
    ports = set(sb.values("Port_Binding", "logical_port"))
    return datapaths - {None}, ports


def assert_scale_southbound(sb, workers):
    expected_datapaths, expected_ports = scale_southbound_names(workers)
    datapaths, ports = southbound_names(sb)
    assert expected_datapaths <= datapaths
    assert expected_ports <= ports


SCALE_CHASSIS = "ovn-scale-0"


def scale_chassis_sync(runner):
    timeout = read_int(os.environ, "OTT_SCALE_CHASSIS_TIMEOUT", 120)
    start = time.monotonic()
    runner.run(
        "ovn-nbctl",
        "--wait=hv",
        f"--timeout={timeout}",
        "sync",
    )
    print(f"Scale chassis sync completed in {time.monotonic() - start:.3f}s.")
    return timeout


def assert_scale_chassis(runner, nb, sb):
    timeout = scale_chassis_sync(runner)
    nb_cfg = nb.value("NB_Global", "nb_cfg")
    row = sb.by_name("Chassis", SCALE_CHASSIS, "_uuid")
    private = sb.by_name("Chassis_Private", SCALE_CHASSIS, "nb_cfg")
    assert private["nb_cfg"] >= nb_cfg
    assert (
        runner.output(
            "ovn-appctl",
            "-t",
            "ovn-controller",
            "connection-status",
        )
        == "connected"
    )

    logical_port = f"cr-rtr-to-node-{SCALE_CHASSIS}"
    runner.wait(
        "ovn-sbctl",
        "--bare",
        "--columns=chassis",
        "find",
        "Port_Binding",
        f"logical_port={logical_port}",
        attempts=timeout * 5,
        interval=0.2,
        until=lambda result, uuid=row["_uuid"]: uuid in result.stdout,
    )
    binding = sb.one(
        "Port_Binding",
        f"logical_port={logical_port}",
        "type=chassisredirect",
        columns=("chassis",),
    )
    assert binding["chassis"] == row["_uuid"]
    return row["_uuid"]


def scale_ports(count):
    result = []
    for index in range(count):
        mac = "02:0a:" + ":".join(
            f"{index >> shift & 255:02x}" for shift in (24, 16, 8, 0)
        )
        result.append(
            {
                "name": f"ovn-scale-pod-{index}",
                "interface": f"osp{index:08x}",
                "chassis": SCALE_CHASSIS,
                "switch": f"lswitch-{SCALE_CHASSIS}",
                "addresses": f"{mac} 16.0.0.{index + 1} 16::{index + 1}",
            }
        )
    return result


def scale_port_rows(nb):
    return nb.find(
        "Logical_Switch_Port",
        f"{OWNER}{json.dumps(f'self-scale-ports:{SCALE_CHASSIS}')}",
        columns=("_uuid", "name", "addresses", "port_security"),
    )


def assert_scale_ports(runner, nb, sb, count, snapshots=None):
    timeout = scale_chassis_sync(runner)
    expected = scale_ports(count)
    rows = {row["name"]: row for row in scale_port_rows(nb)}
    assert set(rows) == {port["name"] for port in expected}

    for port in expected:
        row = rows[port["name"]]
        assert row["addresses"] == port["addresses"]
        assert row["port_security"] == port["addresses"]
        assert nb.referring_names("Logical_Switch", "ports", row["_uuid"]) == [
            port["switch"]
        ]
        chassis = sb.by_name("Chassis", port["chassis"], "_uuid")
        runner.wait(
            "ovn-sbctl",
            "--bare",
            "--columns=chassis",
            "find",
            "Port_Binding",
            f"logical_port={port['name']}",
            attempts=timeout * 5,
            interval=0.2,
            until=lambda result, uuid=chassis["_uuid"]: uuid in result.stdout,
        )
        assert (
            sb.one(
                "Port_Binding",
                f"logical_port={port['name']}",
                columns=("chassis",),
            )["chassis"]
            == chassis["_uuid"]
        )

        assert (
            runner.output(
                "ovs-vsctl",
                "port-to-br",
                port["interface"],
            )
            == "br-int"
        )
        assert (
            runner.output(
                "ovs-vsctl",
                "get",
                "Interface",
                port["interface"],
                "external_ids:iface-id",
            ).strip('"')
            == port["name"]
        )
        if snapshots:
            name = f"scale-port-{port['name']}"
            if snapshots.path(name).exists():
                assert row["_uuid"] == snapshots.load(name)
            else:
                snapshots.save(name, row["_uuid"])


def assert_scale_port_absent(runner, nb, sb, index):
    name = f"ovn-scale-pod-{index}"
    interface = f"osp{index:08x}"
    timeout = read_int(os.environ, "OTT_SCALE_CHASSIS_TIMEOUT", 120)

    assert not nb.exists("Logical_Switch_Port", f"name={name}")
    runner.wait(
        "ovn-sbctl",
        "--bare",
        "--columns=_uuid",
        "find",
        "Port_Binding",
        f"logical_port={name}",
        attempts=timeout * 5,
        interval=0.2,
        until=lambda result: not result.stdout.strip(),
    )
    assert not runner.succeeds(
        "ovs-vsctl",
        "port-to-br",
        interface,
    )


class TestPreconditions:
    def test_northbound_database_is_available(self):
        assert Runner().succeeds("ovn-nbctl", "show")


class TestInitial:
    def test_switches_and_routers(self, nb, snapshots):
        switch = nb.by_name("Logical_Switch", "self-moved", "_uuid", "other_config")
        router = nb.by_name("Logical_Router", "self-r1", "_uuid", "options")

        assert switch["other_config"] == {
            "subnet": "203.0.113.0/24",
            "exclude_ips": "203.0.113.1..203.0.113.2",
            "mcast_snoop": "true",
        }
        assert router["options"] == {
            "chassis": "self-chassis",
            "dynamic_neigh_routers": "true",
            "mac_binding_age_threshold": "5",
        }
        assert nb.by_name("Logical_Switch", "self-sw", "other_config")[
            "other_config"
        ] == {
            "subnet": "192.0.2.0/24",
            "exclude_ips": "192.0.2.1..192.0.2.2",
        }
        assert nb.exists("Logical_Switch", "name=self-unused")
        assert nb.exists("Logical_Router", "name=self-r2")
        assert nb.by_name("Logical_Router", "self-r3", "options")["options"] == {
            "chassis": "clear-me"
        }
        snapshots.save("switch", switch["_uuid"])

    def test_router_ports(self, nb, snapshots):
        port = nb.by_name(
            "Logical_Router_Port",
            "self-rp",
            "_uuid",
            "mac",
            "networks",
            "options",
        )
        switch_port = nb.by_name(
            "Logical_Switch_Port",
            "self-rp-sw",
            "_uuid",
            "type",
            "options",
            "addresses",
        )

        assert port["mac"] == "02:00:00:00:10:01"
        assert sorted(port["networks"]) == [
            "192.0.2.254/24",
            "2001:db8:1::ff/64",
        ]
        assert port["options"] == {
            "gateway_mtu": "1400",
            "redirect-type": "bridged",
        }
        assert switch_port["type"] == "router"
        assert switch_port["options"]["router-port"] == "self-rp"
        assert switch_port["addresses"] == "router"
        assert nb.referring_names("Logical_Router", "ports", port["_uuid"]) == [
            "self-r1"
        ]
        assert nb.referring_names("Logical_Switch", "ports", switch_port["_uuid"]) == [
            "self-sw"
        ]
        assert nb.exists("Logical_Router_Port", "name=self-rp-delete")
        assert nb.exists("Logical_Switch_Port", "name=self-rp-delete-sw")
        snapshots.save("router-port", port["_uuid"])
        snapshots.save("router-switch-port", switch_port["_uuid"])

    def test_localnet_and_gateway_chassis(self, nb, snapshots):
        localnet = nb.by_name(
            "Logical_Switch_Port",
            "self-localnet",
            "_uuid",
            "type",
            "options",
            "tag",
            "addresses",
        )
        gateway = nb.by_name(
            "Gateway_Chassis",
            "self-gateway",
            "_uuid",
            "chassis_name",
            "priority",
        )

        assert localnet["type"] == "localnet"
        assert localnet["options"]["network_name"] == "self-provider"
        assert localnet["tag"] == 100
        assert localnet["addresses"] == "unknown"
        assert nb.referring_names("Logical_Switch", "ports", localnet["_uuid"]) == [
            "self-sw"
        ]
        assert gateway["chassis_name"] == "self-gateway-1"
        assert gateway["priority"] == 20
        assert nb.referring_names(
            "Logical_Router_Port", "gateway_chassis", gateway["_uuid"]
        ) == ["self-rp-gateway"]
        secondary = nb.by_name(
            "Gateway_Chassis",
            "self-gateway-secondary",
            "_uuid",
            "chassis_name",
            "priority",
        )
        assert secondary["chassis_name"] == "self-gateway-backup"
        assert secondary["priority"] == 0
        assert nb.referring_names(
            "Logical_Router_Port", "gateway_chassis", secondary["_uuid"]
        ) == ["self-rp"]
        assert nb.exists("Logical_Switch_Port", "name=self-localnet-delete")
        assert nb.exists("Gateway_Chassis", "name=self-gateway-delete")
        snapshots.save("localnet", localnet["_uuid"])
        snapshots.save("gateway", gateway["_uuid"])

    def test_dhcp_options(self, nb, snapshots):
        dhcp = nb.managed("DHCP_Options", "self-dhcp", "_uuid", "cidr", "options")
        dhcp_v6 = nb.managed("DHCP_Options", "self-dhcp-v6", "_uuid", "cidr", "options")

        assert dhcp["cidr"] == "192.0.2.0/24"
        assert dhcp["options"]["lease_time"] == "3600"
        assert dhcp["options"]["ip_forward_enable"] == "0"
        assert dhcp_v6["cidr"] == "2001:db8:1::/64"
        assert dhcp_v6["options"]["dns_server"] == "2001:db8::53"
        assert nb.exists("DHCP_Options", f"{MANAGED}self-dhcp-delete")
        snapshots.save("dhcp", dhcp["_uuid"])
        snapshots.save("dhcp-v6", dhcp_v6["_uuid"])

    def test_nat_load_balancer_and_route(self, nb, snapshots):
        nat = nb.managed(
            "NAT",
            "self-nat",
            "_uuid",
            "type",
            "external_ip",
            "logical_ip",
            "logical_port",
            "external_mac",
            "external_port_range",
            "gateway_port",
            "match",
            "priority",
            "options",
        )
        load_balancer = nb.managed(
            "Load_Balancer",
            "self-lb",
            "_uuid",
            "protocol",
            "vips",
            "options",
            "selection_fields",
        )
        route = nb.managed(
            "Logical_Router_Static_Route",
            "self-route",
            "_uuid",
            "ip_prefix",
            "nexthop",
            "policy",
            "route_table",
            "output_port",
        )

        assert nat["type"] == "dnat_and_snat"
        assert nat["external_ip"] == "198.51.100.10"
        assert nat["logical_ip"] == "192.0.2.1"
        assert nat["logical_port"] == "self-port1"
        assert nat["external_mac"] == "02:00:00:00:01:01"
        assert nat["external_port_range"] == "10000-20000"
        assert (
            nat["gateway_port"]
            == nb.by_name("Logical_Router_Port", "self-rp", "_uuid")["_uuid"]
        )
        assert nat["match"] == "ip4.src == 192.0.2.0/24"
        assert nat["priority"] == 100
        assert nat["options"] == {"add_route": "true", "stateless": "true"}
        assert nb.referring_names("Logical_Router", "nat", nat["_uuid"]) == ["self-r1"]

        snat = nb.managed(
            "NAT",
            "self-nat-snat",
            "_uuid",
            "type",
            "external_ip",
            "logical_ip",
            "priority",
        )
        assert snat["type"] == "snat"
        assert snat["external_ip"] == "198.51.100.20"
        assert snat["logical_ip"] == "192.0.2.0/24"
        assert snat["priority"] == 0
        assert nb.referring_names("Logical_Router", "nat", snat["_uuid"]) == ["self-r1"]
        assert load_balancer["protocol"] == "udp"
        assert load_balancer["vips"] == {
            "192.0.2.100:80": "192.0.2.1:8080,192.0.2.2:8080",
            "192.0.2.101:80": "192.0.2.3:8080",
        }
        assert load_balancer["options"]["reject"] == "true"
        assert load_balancer["selection_fields"] == "ip_src"
        assert sorted(
            nb.referring_names(
                "Logical_Switch",
                "load_balancer",
                load_balancer["_uuid"],
            )
        ) == ["self-moved", "self-sw"]
        assert nb.referring_names(
            "Logical_Router",
            "load_balancer",
            load_balancer["_uuid"],
        ) == ["self-r1"]
        assert route["ip_prefix"] == "198.51.100.0/24"
        assert route["nexthop"] == "192.0.2.1"
        assert route["policy"] == "src-ip"
        assert route["route_table"] == "blue"
        assert route["output_port"] == "self-rp"
        assert nb.referring_names(
            "Logical_Router", "static_routes", route["_uuid"]
        ) == ["self-r1"]
        assert nb.exists("NAT", f"{MANAGED}self-nat-delete")
        assert nb.exists("Load_Balancer", f"{MANAGED}self-lb-delete")
        assert nb.exists(
            "Logical_Router_Static_Route",
            f"{MANAGED}self-route-delete",
        )
        snapshots.save("nat", nat["_uuid"])
        snapshots.save("nat-snat", snat["_uuid"])
        snapshots.save("load-balancer", load_balancer["_uuid"])
        snapshots.save("route", route["_uuid"])

    def test_acls(self, nb, snapshots):
        acl = nb.managed(
            "ACL",
            "self-acl",
            "_uuid",
            "direction",
            "priority",
            "match",
            "action",
            "name",
            "log",
            "severity",
            "meter",
            "label",
            "tier",
            "options",
        )

        assert acl["direction"] == "from-lport"
        assert acl["priority"] == 1002
        assert acl["match"] == "ip4 || ip6"
        assert acl["action"] == "allow-related"
        assert acl["name"] == "self-acl-log"
        assert acl["log"] is True
        assert acl["severity"] == "info"
        assert acl["meter"] == "self-meter"
        assert acl["label"] == 42
        assert acl["tier"] == 1
        assert acl["options"] == {"apply-after-lb": "true"}
        assert nb.referring_names("Port_Group", "acls", acl["_uuid"]) == ["self-pg"]
        assert nb.referring_names("Logical_Switch", "acls", acl["_uuid"]) == []
        assert nb.exists("ACL", f"{MANAGED}self-acl-delete")
        snapshots.save("acl", acl["_uuid"])


class TestReconfigured:
    @pytest.mark.parametrize(
        ("table", "identifier", "snapshot"),
        [
            ("Logical_Switch_Port", "self-localnet", "localnet-moved"),
            ("Gateway_Chassis", "self-gateway", "gateway-moved"),
        ],
    )
    def test_named_identity_is_recorded(
        self, nb, snapshots, table, identifier, snapshot
    ):
        snapshots.save(
            snapshot,
            nb.by_name(table, identifier, "_uuid")["_uuid"],
        )

    @pytest.mark.parametrize(
        ("table", "identifier", "snapshot"),
        [
            (
                "Logical_Router_Static_Route",
                "self-route",
                "route-moved",
            ),
            ("NAT", "self-nat", "nat-moved"),
            ("DHCP_Options", "self-dhcp", "dhcp-moved"),
            ("ACL", "self-acl", "acl-moved"),
        ],
    )
    def test_managed_identity_is_recorded(
        self, nb, snapshots, table, identifier, snapshot
    ):
        snapshots.save(
            snapshot,
            nb.managed(table, identifier, "_uuid")["_uuid"],
        )


class TestScaleInitial:
    def test_three_workers_are_complete(self, nb, sb):
        assert_scale_counts(nb, 3)
        assert_scale_group_attachments(nb, 3)
        assert_scale_external_vlans(nb, 3)
        assert_scale_southbound(sb, 3)

        assert sorted(
            nb.by_name(
                "Logical_Router_Port",
                "rtr-to-node-ovn-scale-0",
                "networks",
            )["networks"]
        ) == [
            "16.0.255.254/16",
            "16::ffff:ffff:ffff:fffe/64",
        ]
        assert sorted(
            nb.by_name(
                "Logical_Router_Port",
                "gw-to-join-ovn-scale-0",
                "networks",
            )["networks"]
        ) == [
            "30.0.255.253/16",
            "30::ffff:ffff:ffff:fffd/64",
        ]

        route = nb.managed(
            "Logical_Router_Static_Route",
            "self-scale:ovn-scale-0:worker-v4",
            "ip_prefix",
            "nexthop",
            "policy",
        )
        assert route == {
            "ip_prefix": "16.0.0.0/16",
            "nexthop": "30.0.255.253",
            "policy": "src-ip",
        }
        nat = nb.managed(
            "NAT",
            "self-scale:ovn-scale-0:snat-v4",
            "type",
            "external_ip",
            "logical_ip",
        )
        assert nat == {
            "type": "snat",
            "external_ip": "30.0.255.253",
            "logical_ip": "16.0.0.0/4",
        }

    @pytest.mark.parametrize(
        ("table", "name", "snapshot"),
        [
            ("Logical_Switch", "ls-join1", "scale-join"),
            ("Logical_Router", "lr-cluster1", "scale-cluster"),
            (
                "Logical_Router_Port",
                "rtr-to-node-ovn-scale-0",
                "scale-worker-port",
            ),
        ],
    )
    def test_stable_identity_is_recorded(self, nb, snapshots, table, name, snapshot):
        snapshots.save(snapshot, nb.by_name(table, name, "_uuid")["_uuid"])


class TestScaleExpanded:
    def test_500_workers_are_complete(self, nb, sb, snapshots):
        assert_scale_counts(nb, 500)
        assert_scale_group_attachments(nb, 500)
        assert_scale_external_vlans(nb, 500)
        assert_scale_southbound(sb, 500)
        assert nb.by_name("Logical_Switch", "ls-join1", "_uuid")[
            "_uuid"
        ] == snapshots.load("scale-join")
        assert nb.by_name("Logical_Router", "lr-cluster1", "_uuid")[
            "_uuid"
        ] == snapshots.load("scale-cluster")
        assert nb.by_name(
            "Logical_Router_Port",
            "rtr-to-node-ovn-scale-0",
            "_uuid",
        )["_uuid"] == snapshots.load("scale-worker-port")
        assert sorted(
            nb.by_name(
                "Logical_Router_Port",
                "rtr-to-node-ovn-scale-499",
                "networks",
            )["networks"]
        ) == [
            "16::1f3:ffff:ffff:ffff:fffe/64",
            "17.243.255.254/16",
        ]


class TestScaleChassisInitial:
    def test_chassis_guest_is_connected(self, runner, nb, sb, snapshots):
        snapshots.save("scale-chassis", assert_scale_chassis(runner, nb, sb))


class TestScaleChassisExpanded:
    def test_chassis_guest_processes_500_worker_topology(
        self, runner, nb, sb, snapshots
    ):
        assert assert_scale_chassis(runner, nb, sb) == snapshots.load("scale-chassis")


class TestScalePortsInitial:
    def test_three_ports_are_bound(self, runner, nb, sb, snapshots):
        assert_scale_ports(runner, nb, sb, 3, snapshots)


class TestScalePortsExpanded:
    def test_reapply_preserves_three_bound_ports(self, runner, nb, sb, snapshots):
        assert_scale_ports(runner, nb, sb, 3, snapshots)


class TestScalePortsContracted:
    def test_two_ports_remain_bound(self, runner, nb, sb, snapshots):
        assert_scale_ports(runner, nb, sb, 2, snapshots)

    def test_removed_port_leaves_no_stale_state(self, runner, nb, sb):
        assert_scale_port_absent(runner, nb, sb, 2)


class TestResult:
    def test_switches_and_routers(self, nb, snapshots):
        switch = nb.by_name("Logical_Switch", "self-moved", "_uuid", "other_config")
        router = nb.by_name("Logical_Router", "self-r1", "options")

        assert switch["other_config"] == {
            "subnet": "198.51.100.0/24",
            "mcast_snoop": "false",
        }
        assert switch["_uuid"] == snapshots.load("switch")
        assert nb.by_name("Logical_Switch", "self-sw", "other_config")[
            "other_config"
        ] == {
            "subnet": "192.0.2.0/24",
            "exclude_ips": "192.0.2.1..192.0.2.2",
        }
        assert not nb.exists("Logical_Switch", "name=self-unused")
        assert router["options"] == {
            "chassis": "moved-chassis",
            "mac_binding_age_threshold": "10",
        }
        assert not nb.exists("Logical_Router", "name=self-r2")
        assert nb.by_name("Logical_Router", "self-r3", "options")["options"] == {}

    def test_router_port_moved_without_recreation(self, nb, snapshots):
        port = nb.by_name(
            "Logical_Router_Port",
            "self-rp",
            "_uuid",
            "mac",
            "networks",
            "options",
        )
        switch_port = nb.by_name(
            "Logical_Switch_Port",
            "self-rp-sw",
            "_uuid",
            "type",
            "options",
            "addresses",
        )

        assert port["_uuid"] == snapshots.load("router-port")
        assert switch_port["_uuid"] == snapshots.load("router-switch-port")
        assert port["mac"] == "02:00:00:00:10:03"
        assert sorted(port["networks"]) == [
            "2001:db8:2::ff/64",
            "203.0.113.1/24",
        ]
        assert port["options"] == {"gateway_mtu": "1300"}
        assert switch_port["type"] == "router"
        assert switch_port["options"] == {"router-port": "self-rp"}
        assert switch_port["addresses"] == "router"
        assert nb.referring_names("Logical_Router", "ports", port["_uuid"]) == [
            "self-r3"
        ]
        assert nb.referring_names("Logical_Switch", "ports", switch_port["_uuid"]) == [
            "self-moved"
        ]
        assert not nb.exists("Logical_Router_Port", "name=self-rp-delete")
        assert not nb.exists("Logical_Switch_Port", "name=self-rp-delete-sw")

    def test_localnet_and_gateway_reconfiguration(self, nb, snapshots):
        localnet = nb.by_name(
            "Logical_Switch_Port",
            "self-localnet",
            "_uuid",
            "type",
            "options",
            "tag",
            "addresses",
        )
        gateway = nb.by_name(
            "Gateway_Chassis",
            "self-gateway",
            "_uuid",
            "chassis_name",
            "priority",
        )

        assert localnet["type"] == "localnet"
        assert localnet["options"]["network_name"] == "self-provider-moved"
        assert localnet["tag"] == []
        assert localnet["addresses"] == "unknown"
        assert nb.referring_names("Logical_Switch", "ports", localnet["_uuid"]) == [
            "self-moved"
        ]
        assert localnet["_uuid"] == snapshots.load("localnet")
        assert localnet["_uuid"] == snapshots.load("localnet-moved")
        assert gateway["chassis_name"] == "self-gateway-2"
        assert gateway["priority"] == 30
        assert nb.referring_names(
            "Logical_Router_Port", "gateway_chassis", gateway["_uuid"]
        ) == ["self-rp"]
        assert gateway["_uuid"] == snapshots.load("gateway")
        assert gateway["_uuid"] == snapshots.load("gateway-moved")
        secondary = nb.by_name(
            "Gateway_Chassis",
            "self-gateway-secondary",
            "_uuid",
            "chassis_name",
            "priority",
        )
        assert secondary["chassis_name"] == "self-gateway-backup"
        assert secondary["priority"] == 10
        assert nb.referring_names(
            "Logical_Router_Port", "gateway_chassis", secondary["_uuid"]
        ) == ["self-rp"]
        assert not nb.exists("Gateway_Chassis", "name=self-gateway-delete")
        unmanaged_gateway = nb.one(
            "Gateway_Chassis",
            "chassis_name=self-gateway-unmanaged",
            columns=("_uuid",),
        )
        assert nb.referring_names(
            "Logical_Router_Port",
            "gateway_chassis",
            unmanaged_gateway["_uuid"],
        ) == ["self-rp-gateway"]
        assert not nb.exists("Logical_Switch_Port", "name=self-localnet-delete")
        assert nb.exists("Logical_Switch_Port", "name=self-localnet-unmanaged")

    def test_dhcp_reconfiguration(self, nb, snapshots):
        dhcp = nb.managed("DHCP_Options", "self-dhcp", "_uuid", "cidr", "options")
        dhcp_v6 = nb.managed("DHCP_Options", "self-dhcp-v6", "_uuid", "cidr", "options")

        assert dhcp["cidr"] == "198.51.100.0/24"
        assert dhcp["options"] == {
            "classless_static_route": "{0.0.0.0/0, 198.51.100.1}",
            "dns_server": "198.51.100.53",
            "ip_forward_enable": "1",
            "lease_time": "7200",
            "server_id": "198.51.100.1",
        }
        assert dhcp["_uuid"] == snapshots.load("dhcp")
        assert dhcp["_uuid"] == snapshots.load("dhcp-moved")
        assert dhcp_v6["_uuid"] == snapshots.load("dhcp-v6")
        assert dhcp_v6["cidr"] == "2001:db8:1::/64"
        assert dhcp_v6["options"]["dns_server"] == "2001:db8::53"
        assert not nb.exists("DHCP_Options", f"{MANAGED}self-dhcp-delete")
        assert nb.exists("DHCP_Options", "cidr=10.10.0.0/24")

    def test_acl_reconfiguration(self, nb, snapshots):
        acl = nb.managed(
            "ACL",
            "self-acl",
            "_uuid",
            "direction",
            "priority",
            "match",
            "action",
            "name",
            "log",
            "severity",
            "meter",
            "label",
            "tier",
            "options",
        )

        assert acl["_uuid"] == snapshots.load("acl")
        assert acl["_uuid"] == snapshots.load("acl-moved")
        assert acl["direction"] == "to-lport"
        assert acl["priority"] == 1100
        assert acl["match"] == "ip4"
        assert acl["action"] == "reject"
        assert acl["name"] == []
        assert acl["log"] is False
        assert acl["severity"] == []
        assert acl["meter"] == []
        assert acl["label"] == 0
        assert acl["tier"] == 2
        assert acl["options"] == {}
        assert nb.referring_names("Logical_Switch", "acls", acl["_uuid"]) == [
            "self-moved"
        ]
        assert nb.referring_names("Port_Group", "acls", acl["_uuid"]) == []
        assert not nb.exists("ACL", f"{MANAGED}self-acl-delete")
        unmanaged = nb.one(
            "ACL",
            "priority=800",
            f"match={json.dumps('ip4.src == 192.0.2.0/24')}",
            columns=("_uuid",),
        )
        assert nb.referring_names("Logical_Switch", "acls", unmanaged["_uuid"]) == [
            "self-sw"
        ]

    def test_nat_load_balancer_and_route(self, nb, snapshots):
        nat = nb.managed(
            "NAT",
            "self-nat",
            "_uuid",
            "type",
            "external_ip",
            "logical_ip",
            "logical_port",
            "external_mac",
            "external_port_range",
            "gateway_port",
            "match",
            "priority",
            "options",
        )
        load_balancer = nb.managed(
            "Load_Balancer",
            "self-lb",
            "_uuid",
            "protocol",
            "vips",
            "options",
            "selection_fields",
        )
        route = nb.managed(
            "Logical_Router_Static_Route",
            "self-route",
            "_uuid",
            "ip_prefix",
            "nexthop",
            "policy",
            "route_table",
            "output_port",
        )

        assert nat["type"] == "dnat"
        assert nat["external_ip"] == "2001:db8:ffff::10"
        assert nat["logical_ip"] == "2001:db8:2::1"
        assert nat["logical_port"] == []
        assert nat["external_mac"] == []
        assert nat["external_port_range"] == ""
        assert nat["gateway_port"] == []
        assert nat["match"] == ""
        assert nat["priority"] == 0
        assert nat["options"] == {}
        assert nat["_uuid"] == snapshots.load("nat")
        assert nat["_uuid"] == snapshots.load("nat-moved")
        assert nb.referring_names("Logical_Router", "nat", nat["_uuid"]) == ["self-r3"]
        assert not nb.exists("NAT", f"{MANAGED}self-nat-delete")
        snat = nb.managed(
            "NAT",
            "self-nat-snat",
            "_uuid",
            "type",
            "external_ip",
            "logical_ip",
        )
        assert snat["_uuid"] == snapshots.load("nat-snat")
        assert snat["type"] == "snat"
        assert snat["external_ip"] == "198.51.100.20"
        assert snat["logical_ip"] == "192.0.2.0/24"
        assert nb.referring_names("Logical_Router", "nat", snat["_uuid"]) == ["self-r1"]
        unmanaged_nat = nb.one(
            "NAT",
            "external_ip=203.0.113.20",
            "logical_ip=10.0.0.0/24",
            columns=("_uuid",),
        )
        assert nb.referring_names("Logical_Router", "nat", unmanaged_nat["_uuid"]) == [
            "self-r3"
        ]
        assert load_balancer["protocol"] == "tcp"
        assert load_balancer["vips"] == {"198.51.100.100:443": "198.51.100.10:8443"}
        assert load_balancer["options"] == {"reject": "false"}
        assert load_balancer["selection_fields"] == "ip_dst"
        assert load_balancer["_uuid"] == snapshots.load("load-balancer")
        assert nb.referring_names(
            "Logical_Switch",
            "load_balancer",
            load_balancer["_uuid"],
        ) == ["self-moved"]
        assert nb.referring_names(
            "Logical_Router",
            "load_balancer",
            load_balancer["_uuid"],
        ) == ["self-r3"]
        assert not nb.exists("Load_Balancer", f"{MANAGED}self-lb-delete")
        assert route["ip_prefix"] == "2001:db8:ffff::/64"
        assert route["nexthop"] == "2001:db8:2::1"
        assert route["policy"] == "dst-ip"
        assert route["route_table"] == ""
        assert route["output_port"] == []
        assert route["_uuid"] == snapshots.load("route")
        assert route["_uuid"] == snapshots.load("route-moved")
        assert nb.referring_names(
            "Logical_Router", "static_routes", route["_uuid"]
        ) == ["self-r3"]
        assert not nb.exists(
            "Logical_Router_Static_Route",
            f"{MANAGED}self-route-delete",
        )
        unmanaged_route = nb.one(
            "Logical_Router_Static_Route",
            "ip_prefix=192.0.2.0/24",
            "nexthop=203.0.113.2",
            columns=("_uuid",),
        )
        assert nb.referring_names(
            "Logical_Router",
            "static_routes",
            unmanaged_route["_uuid"],
        ) == ["self-r3"]


class TestScaleResult:
    def test_contracted_topology_is_complete(self, nb, sb, snapshots):
        assert_scale_counts(nb, 2)
        assert_scale_group_attachments(nb, 2)
        assert_scale_external_vlans(nb, 2)
        assert_scale_southbound(sb, 2)
        assert nb.by_name("Logical_Switch", "ls-join1", "_uuid")[
            "_uuid"
        ] == snapshots.load("scale-join")
        assert nb.by_name("Logical_Router", "lr-cluster1", "_uuid")[
            "_uuid"
        ] == snapshots.load("scale-cluster")
        assert nb.by_name(
            "Logical_Router_Port",
            "rtr-to-node-ovn-scale-0",
            "_uuid",
        )["_uuid"] == snapshots.load("scale-worker-port")

    def test_removed_workers_leave_no_southbound_topology(self, sb):
        current_datapaths, current_ports = scale_southbound_names(2)
        expanded_datapaths, expanded_ports = scale_southbound_names(500)
        datapaths, ports = southbound_names(sb)

        assert not (expanded_datapaths - current_datapaths) & datapaths
        assert not (expanded_ports - current_ports) & ports

    @pytest.mark.parametrize(
        "name",
        ["ovn-scale-2", "ovn-scale-3", "ovn-scale-4"],
    )
    def test_removed_workers_leave_no_topology(self, nb, name):
        assert not nb.exists("Logical_Switch", f"name=lswitch-{name}")
        assert not nb.exists("Logical_Switch", f"name=ext-{name}")
        assert not nb.exists("Logical_Router", f"name=gwrouter-{name}")
        assert not nb.exists(
            "Logical_Router_Port",
            f"name=rtr-to-node-{name}",
        )
        assert not scale_managed_rows(nb, "NAT") or all(
            name not in row["external_ids"]["ovn-tmt-tests-id"]
            for row in scale_managed_rows(nb, "NAT")
        )


class TestScaleChassisResult:
    def test_chassis_guest_processes_contracted_topology(
        self, runner, nb, sb, snapshots
    ):
        assert assert_scale_chassis(runner, nb, sb) == snapshots.load("scale-chassis")


class TestScalePortsResult:
    def test_two_ports_remain_bound(self, runner, nb, sb, snapshots):
        assert_scale_ports(runner, nb, sb, 2, snapshots)

    def test_removed_port_remains_absent(self, runner, nb, sb):
        assert_scale_port_absent(runner, nb, sb, 2)
