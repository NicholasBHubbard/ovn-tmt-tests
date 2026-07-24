import pytest

from ovn_test.command import Runner
from ovn_test.ovsdb import Ovsdb


MANAGED = "external_ids:ovn-tmt-tests-id="


@pytest.fixture
def nb():
    return Ovsdb(Runner(), "ovn-nbctl")


def named(nb, table, name, *columns):
    return nb.one(table, f"name={name}", columns=columns)


def managed(nb, table, identifier, *columns):
    return nb.one(table, f"{MANAGED}{identifier}", columns=columns)


def names(nb, table, *conditions):
    return [row["name"] for row in nb.find(table, *conditions, columns=("name",))]


def attached_to(nb, table, column, uuid):
    return names(nb, table, f"{column}{{>=}}{uuid}")


class TestPreconditions:
    def test_northbound_database_is_available(self):
        assert Runner().succeeds("ovn-nbctl", "show")


class TestInitial:
    def test_switches_and_routers(self, nb, snapshots):
        switch = named(nb, "Logical_Switch", "self-moved", "_uuid", "other_config")
        router = named(nb, "Logical_Router", "self-r1", "_uuid", "options")

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
        assert named(nb, "Logical_Switch", "self-sw", "other_config")[
            "other_config"
        ] == {
            "subnet": "192.0.2.0/24",
            "exclude_ips": "192.0.2.1..192.0.2.2",
        }
        assert nb.exists("Logical_Switch", "name=self-unused")
        assert nb.exists("Logical_Router", "name=self-r2")
        assert named(nb, "Logical_Router", "self-r3", "options")["options"] == {
            "chassis": "clear-me"
        }
        snapshots.save("switch", switch["_uuid"])

    def test_router_ports(self, nb, snapshots):
        port = named(
            nb,
            "Logical_Router_Port",
            "self-rp",
            "_uuid",
            "mac",
            "networks",
            "options",
        )
        switch_port = named(
            nb,
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
        assert attached_to(nb, "Logical_Router", "ports", port["_uuid"]) == ["self-r1"]
        assert attached_to(nb, "Logical_Switch", "ports", switch_port["_uuid"]) == [
            "self-sw"
        ]
        assert nb.exists("Logical_Router_Port", "name=self-rp-delete")
        assert nb.exists("Logical_Switch_Port", "name=self-rp-delete-sw")
        snapshots.save("router-port", port["_uuid"])
        snapshots.save("router-switch-port", switch_port["_uuid"])

    def test_localnet_and_gateway_chassis(self, nb, snapshots):
        localnet = named(
            nb,
            "Logical_Switch_Port",
            "self-localnet",
            "_uuid",
            "type",
            "options",
            "tag",
            "addresses",
        )
        gateway = named(
            nb,
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
        assert attached_to(nb, "Logical_Switch", "ports", localnet["_uuid"]) == [
            "self-sw"
        ]
        assert gateway["chassis_name"] == "self-gateway-1"
        assert gateway["priority"] == 20
        assert attached_to(
            nb, "Logical_Router_Port", "gateway_chassis", gateway["_uuid"]
        ) == ["self-rp-gateway"]
        secondary = named(
            nb,
            "Gateway_Chassis",
            "self-gateway-secondary",
            "_uuid",
            "chassis_name",
            "priority",
        )
        assert secondary["chassis_name"] == "self-gateway-backup"
        assert secondary["priority"] == 0
        assert attached_to(
            nb, "Logical_Router_Port", "gateway_chassis", secondary["_uuid"]
        ) == ["self-rp"]
        assert nb.exists("Logical_Switch_Port", "name=self-localnet-delete")
        assert nb.exists("Gateway_Chassis", "name=self-gateway-delete")
        snapshots.save("localnet", localnet["_uuid"])
        snapshots.save("gateway", gateway["_uuid"])

    def test_dhcp_options(self, nb, snapshots):
        dhcp = managed(nb, "DHCP_Options", "self-dhcp", "_uuid", "cidr", "options")
        dhcp_v6 = managed(
            nb, "DHCP_Options", "self-dhcp-v6", "_uuid", "cidr", "options"
        )

        assert dhcp["cidr"] == "192.0.2.0/24"
        assert dhcp["options"]["lease_time"] == "3600"
        assert dhcp["options"]["ip_forward_enable"] == "0"
        assert dhcp_v6["cidr"] == "2001:db8:1::/64"
        assert dhcp_v6["options"]["dns_server"] == "2001:db8::53"
        assert nb.exists("DHCP_Options", f"{MANAGED}self-dhcp-delete")
        snapshots.save("dhcp", dhcp["_uuid"])
        snapshots.save("dhcp-v6", dhcp_v6["_uuid"])

    def test_nat_load_balancer_and_route(self, nb, snapshots):
        nat = managed(
            nb,
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
        load_balancer = managed(
            nb,
            "Load_Balancer",
            "self-lb",
            "_uuid",
            "protocol",
            "vips",
            "options",
            "selection_fields",
        )
        route = managed(
            nb,
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
            == named(nb, "Logical_Router_Port", "self-rp", "_uuid")["_uuid"]
        )
        assert nat["match"] == "ip4.src == 192.0.2.0/24"
        assert nat["priority"] == 100
        assert nat["options"] == {"add_route": "true", "stateless": "true"}
        assert attached_to(nb, "Logical_Router", "nat", nat["_uuid"]) == ["self-r1"]

        snat = managed(
            nb,
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
        assert attached_to(nb, "Logical_Router", "nat", snat["_uuid"]) == ["self-r1"]
        assert load_balancer["protocol"] == "udp"
        assert load_balancer["vips"] == {
            "192.0.2.100:80": "192.0.2.1:8080,192.0.2.2:8080",
            "192.0.2.101:80": "192.0.2.3:8080",
        }
        assert load_balancer["options"]["reject"] == "true"
        assert load_balancer["selection_fields"] == "ip_src"
        assert sorted(
            attached_to(
                nb,
                "Logical_Switch",
                "load_balancer",
                load_balancer["_uuid"],
            )
        ) == ["self-moved", "self-sw"]
        assert attached_to(
            nb,
            "Logical_Router",
            "load_balancer",
            load_balancer["_uuid"],
        ) == ["self-r1"]
        assert route["ip_prefix"] == "198.51.100.0/24"
        assert route["nexthop"] == "192.0.2.1"
        assert route["policy"] == "src-ip"
        assert route["route_table"] == "blue"
        assert route["output_port"] == "self-rp"
        assert attached_to(nb, "Logical_Router", "static_routes", route["_uuid"]) == [
            "self-r1"
        ]
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
        acl = managed(
            nb,
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
        assert attached_to(nb, "Port_Group", "acls", acl["_uuid"]) == ["self-pg"]
        assert attached_to(nb, "Logical_Switch", "acls", acl["_uuid"]) == []
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
            named(nb, table, identifier, "_uuid")["_uuid"],
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
            managed(nb, table, identifier, "_uuid")["_uuid"],
        )


class TestResult:
    def test_switches_and_routers(self, nb, snapshots):
        switch = named(nb, "Logical_Switch", "self-moved", "_uuid", "other_config")
        router = named(nb, "Logical_Router", "self-r1", "options")

        assert switch["other_config"] == {
            "subnet": "198.51.100.0/24",
            "mcast_snoop": "false",
        }
        assert switch["_uuid"] == snapshots.load("switch")
        assert named(nb, "Logical_Switch", "self-sw", "other_config")[
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
        assert named(nb, "Logical_Router", "self-r3", "options")["options"] == {}

    def test_router_port_moved_without_recreation(self, nb, snapshots):
        port = named(
            nb,
            "Logical_Router_Port",
            "self-rp",
            "_uuid",
            "mac",
            "networks",
            "options",
        )
        switch_port = named(
            nb,
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
        assert attached_to(nb, "Logical_Router", "ports", port["_uuid"]) == ["self-r3"]
        assert attached_to(nb, "Logical_Switch", "ports", switch_port["_uuid"]) == [
            "self-moved"
        ]
        assert not nb.exists("Logical_Router_Port", "name=self-rp-delete")
        assert not nb.exists("Logical_Switch_Port", "name=self-rp-delete-sw")

    def test_localnet_and_gateway_reconfiguration(self, nb, snapshots):
        localnet = named(
            nb,
            "Logical_Switch_Port",
            "self-localnet",
            "_uuid",
            "type",
            "options",
            "tag",
            "addresses",
        )
        gateway = named(
            nb,
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
        assert attached_to(nb, "Logical_Switch", "ports", localnet["_uuid"]) == [
            "self-moved"
        ]
        assert localnet["_uuid"] == snapshots.load("localnet")
        assert localnet["_uuid"] == snapshots.load("localnet-moved")
        assert gateway["chassis_name"] == "self-gateway-2"
        assert gateway["priority"] == 30
        assert attached_to(
            nb, "Logical_Router_Port", "gateway_chassis", gateway["_uuid"]
        ) == ["self-rp"]
        assert gateway["_uuid"] == snapshots.load("gateway")
        assert gateway["_uuid"] == snapshots.load("gateway-moved")
        secondary = named(
            nb,
            "Gateway_Chassis",
            "self-gateway-secondary",
            "_uuid",
            "chassis_name",
            "priority",
        )
        assert secondary["chassis_name"] == "self-gateway-backup"
        assert secondary["priority"] == 10
        assert attached_to(
            nb, "Logical_Router_Port", "gateway_chassis", secondary["_uuid"]
        ) == ["self-rp"]
        assert not nb.exists("Gateway_Chassis", "name=self-gateway-delete")
        unmanaged_gateway = nb.one(
            "Gateway_Chassis",
            "chassis_name=self-gateway-unmanaged",
            columns=("_uuid",),
        )
        assert attached_to(
            nb,
            "Logical_Router_Port",
            "gateway_chassis",
            unmanaged_gateway["_uuid"],
        ) == ["self-rp-gateway"]
        assert not nb.exists("Logical_Switch_Port", "name=self-localnet-delete")
        assert nb.exists("Logical_Switch_Port", "name=self-localnet-unmanaged")

    def test_dhcp_reconfiguration(self, nb, snapshots):
        dhcp = managed(nb, "DHCP_Options", "self-dhcp", "_uuid", "cidr", "options")
        dhcp_v6 = managed(
            nb, "DHCP_Options", "self-dhcp-v6", "_uuid", "cidr", "options"
        )

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
        acl = managed(
            nb,
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
        assert attached_to(nb, "Logical_Switch", "acls", acl["_uuid"]) == ["self-moved"]
        assert attached_to(nb, "Port_Group", "acls", acl["_uuid"]) == []
        assert not nb.exists("ACL", f"{MANAGED}self-acl-delete")
        unmanaged = nb.one(
            "ACL",
            "priority=800",
            "match=ip4.src == 192.0.2.0/24",
            columns=("_uuid",),
        )
        assert attached_to(nb, "Logical_Switch", "acls", unmanaged["_uuid"]) == [
            "self-sw"
        ]

    def test_nat_load_balancer_and_route(self, nb, snapshots):
        nat = managed(
            nb,
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
        load_balancer = managed(
            nb,
            "Load_Balancer",
            "self-lb",
            "_uuid",
            "protocol",
            "vips",
            "options",
            "selection_fields",
        )
        route = managed(
            nb,
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
        assert attached_to(nb, "Logical_Router", "nat", nat["_uuid"]) == ["self-r3"]
        assert not nb.exists("NAT", f"{MANAGED}self-nat-delete")
        snat = managed(
            nb,
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
        assert attached_to(nb, "Logical_Router", "nat", snat["_uuid"]) == ["self-r1"]
        unmanaged_nat = nb.one(
            "NAT",
            "external_ip=203.0.113.20",
            "logical_ip=10.0.0.0/24",
            columns=("_uuid",),
        )
        assert attached_to(nb, "Logical_Router", "nat", unmanaged_nat["_uuid"]) == [
            "self-r3"
        ]
        assert load_balancer["protocol"] == "tcp"
        assert load_balancer["vips"] == {"198.51.100.100:443": "198.51.100.10:8443"}
        assert load_balancer["options"] == {"reject": "false"}
        assert load_balancer["selection_fields"] == "ip_dst"
        assert load_balancer["_uuid"] == snapshots.load("load-balancer")
        assert attached_to(
            nb,
            "Logical_Switch",
            "load_balancer",
            load_balancer["_uuid"],
        ) == ["self-moved"]
        assert attached_to(
            nb,
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
        assert attached_to(nb, "Logical_Router", "static_routes", route["_uuid"]) == [
            "self-r3"
        ]
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
        assert attached_to(
            nb,
            "Logical_Router",
            "static_routes",
            unmanaged_route["_uuid"],
        ) == ["self-r3"]
