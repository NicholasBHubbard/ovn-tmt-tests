import math
import time
from pathlib import Path


CREATE_ENDPOINT = """\
set -euxo pipefail
namespace=$1
host_interface=$2
port=$3
mac=$4
ipv4=$5
ipv6=$6
enable_ipv4=$7
enable_ipv6=$8
mtu=$9

ovs-vsctl --if-exists del-port br-int "$host_interface"
ip link delete "$host_interface" 2>/dev/null || true
ip netns delete "$namespace" 2>/dev/null || true
ip netns add "$namespace"
ip link add "$host_interface" type veth peer name "${namespace}-n"
ip link set "${namespace}-n" netns "$namespace"
ip -n "$namespace" link set "${namespace}-n" name eth0
ip link set "$host_interface" mtu "$mtu" up
ip -n "$namespace" link set lo up
ip -n "$namespace" link set eth0 address "$mac" mtu "$mtu" up

if [ "$enable_ipv4" = true ]; then
    ip -n "$namespace" address replace "$ipv4/16" dev eth0
fi
if [ "$enable_ipv6" = true ]; then
    ip -n "$namespace" -6 address replace "$ipv6/64" dev eth0 nodad
fi

ovs-vsctl --may-exist add-port br-int "$host_interface" \
    -- set Interface "$host_interface" external_ids:iface-id="$port"
"""


REMOVE_ENDPOINT = """\
set -euxo pipefail
namespace=$1
host_interface=$2
ovs-vsctl --if-exists del-port br-int "$host_interface"
ip link delete "$host_interface" 2>/dev/null || true
ip netns delete "$namespace" 2>/dev/null || true
"""


VERIFY_ENDPOINT_REMOVED = """\
set -euxo pipefail
test ! -e "/var/run/netns/$1"
! ovs-vsctl port-to-br "$2" >/dev/null 2>&1
"""


def _positive(name, value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _validate_common(initial, iterations, timeout, ipv4, ipv6, mtu, chassis, total):
    for name, value in (
        ("initial", initial),
        ("iterations", iterations),
        ("timeout", timeout),
        ("mtu", mtu),
        ("chassis", chassis),
    ):
        _positive(name, value)
    if not isinstance(ipv4, bool) or not isinstance(ipv6, bool):
        raise ValueError("IP family settings must be booleans")
    if not ipv4 and not ipv6:
        raise ValueError("at least one IP family must be enabled")
    if chassis < 2 or initial < chassis:
        raise ValueError(
            "the workload requires at least one initial endpoint per chassis"
        )
    minimum_mtu = 1280 if ipv6 else 576
    if not minimum_mtu <= mtu <= 65535:
        raise ValueError(f"MTU must be between {minimum_mtu} and 65535")
    if total > 65534:
        raise ValueError("the workload exceeds its endpoint address space")


def validate_light(initial, iterations, timeout, ipv4, ipv6, mtu, chassis):
    _validate_common(
        initial,
        iterations,
        timeout,
        ipv4,
        ipv6,
        mtu,
        chassis,
        initial + iterations,
    )


def validate_heavy(
    initial,
    iterations,
    pods_per_service,
    protocols,
    timeout,
    ipv4,
    ipv6,
    mtu,
    chassis,
):
    _positive("pods_per_service", pods_per_service)
    if initial % pods_per_service:
        raise ValueError("initial pods must contain complete services")
    if len(protocols) != len(set(protocols)) or not protocols:
        raise ValueError("load-balancer protocols must be unique")
    if set(protocols) - {"tcp", "udp", "sctp"}:
        raise ValueError("load-balancer protocols must be tcp, udp or sctp")
    _validate_common(
        initial,
        iterations,
        timeout,
        ipv4,
        ipv6,
        mtu,
        chassis,
        initial + iterations * pods_per_service,
    )


class Workload:
    def __init__(
        self,
        runner,
        computes,
        name,
        prefix,
        metrics_file,
        ipv4=True,
        ipv6=True,
        mtu=1342,
        timeout=60,
    ):
        self.runner = runner
        self.computes = computes
        self.name = name
        self.prefix = prefix
        self.ipv4_enabled = ipv4
        self.ipv6_enabled = ipv6
        self.mtu = mtu
        self.timeout = timeout
        self.endpoints = []
        self.load_balancers = []
        self.cleaned = False

        suffix = name.replace("-", "_")
        self.port_groups = [
            f"pg_{suffix}",
            f"pg_deny_igr_{suffix}",
            f"pg_deny_egr_{suffix}",
        ]
        self.address_sets = [f"as_{suffix}", f"as6_{suffix}"]
        self.address_set_ids = [None, None]
        self.metrics_file = Path(metrics_file)
        self.metrics_file.parent.mkdir(parents=True, exist_ok=True)
        self.metrics_file.write_text("iteration,phase,duration_ns\n")

    def endpoint(self, index):
        value = index + 1
        return {
            "guest": self.computes[index % len(self.computes)],
            "namespace": f"{self.prefix}{index:05d}",
            "interface": f"{self.prefix}{index:05d}-p",
            "port": f"{self.name}-{index:05d}",
            "mac": "02:00:{:02x}:{:02x}:{:02x}:{:02x}".format(
                value >> 24 & 255,
                value >> 16 & 255,
                value >> 8 & 255,
                value & 255,
            ),
            "ipv4": f"10.240.{value >> 8 & 255}.{value & 255}",
            "ipv6": f"fd00:240::{value:x}",
        }

    def service_name(self, service, protocol, family):
        return f"{self.name}-{service:05d}-{protocol}-v{family}"

    @staticmethod
    def vip(service, family):
        value = service + 1
        if family == 4:
            return f"100.0.{value >> 8 & 255}.{value & 255}"
        return f"100::{value:x}"

    def record_metric(self, iteration, phase, start):
        duration = time.time_ns() - start
        with self.metrics_file.open("a") as output:
            output.write(f"{iteration},{phase},{duration}\n")
        print(f"metric iteration={iteration} phase={phase} duration_ns={duration}")

    def measure(self, iteration, phase, action):
        start = time.time_ns()
        result = action()
        self.record_metric(iteration, phase, start)
        return result

    def _destroy_named(self, table, name):
        output = self.runner.output(
            "ovn-nbctl",
            "--bare",
            "--columns=_uuid",
            "find",
            table,
            f"name={name}",
        )
        for uuid in output.split():
            self.runner.run("ovn-nbctl", "destroy", table, uuid)

    def create_topology(self):
        self._destroy_named("Logical_Switch", self.name)
        self.runner.run("ovn-nbctl", "ls-add", self.name)
        for port_group in self.port_groups:
            self._destroy_named("Port_Group", port_group)
            self.runner.run("ovn-nbctl", "pg-add", port_group)
        for family, enabled in enumerate((self.ipv4_enabled, self.ipv6_enabled)):
            if not enabled:
                continue
            name = self.address_sets[family]
            self._destroy_named("Address_Set", name)
            address_set_id = self.runner.output(
                "ovn-nbctl",
                "create",
                "Address_Set",
                f"name={name}",
                f"external_ids:ovn-tmt-tests-owner={self.name}",
            )
            self.address_set_ids[family] = address_set_id

    def add_endpoint(self, index, phase):
        endpoint = self.endpoint(index)
        self.endpoints.append(endpoint)
        addresses = [endpoint["mac"]]
        if self.ipv4_enabled:
            addresses.append(endpoint["ipv4"])
        if self.ipv6_enabled:
            addresses.append(endpoint["ipv6"])

        start = time.time_ns()
        self.runner.run(
            "ovn-nbctl",
            "--may-exist",
            "lsp-add",
            self.name,
            endpoint["port"],
            "--",
            "lsp-set-addresses",
            endpoint["port"],
            " ".join(addresses),
        )
        port_uuid = self.runner.output(
            "ovn-nbctl",
            "--bare",
            "--columns=_uuid",
            "find",
            "Logical_Switch_Port",
            f"name={endpoint['port']}",
        )
        if not port_uuid:
            raise RuntimeError(
                f"logical switch port was not created: {endpoint['port']}"
            )
        self.runner.run(
            "ovn-nbctl",
            "add",
            "Port_Group",
            self.port_groups[0],
            "ports",
            port_uuid,
        )
        for family, enabled in enumerate((self.ipv4_enabled, self.ipv6_enabled)):
            if enabled:
                address = endpoint[f"ipv{family * 2 + 4}"]
                self.runner.run(
                    "ovn-nbctl",
                    "add",
                    "Address_Set",
                    self.address_set_ids[family],
                    "addresses",
                    f'"{address}"',
                )
        self.record_metric(index, f"{phase}_nb", start)

        start = time.time_ns()
        self.runner.run(
            "bash",
            "-s",
            "--",
            endpoint["namespace"],
            endpoint["interface"],
            endpoint["port"],
            endpoint["mac"],
            endpoint["ipv4"],
            endpoint["ipv6"],
            str(self.ipv4_enabled).lower(),
            str(self.ipv6_enabled).lower(),
            str(self.mtu),
            guest=endpoint["guest"],
            input=CREATE_ENDPOINT,
        )
        self.record_metric(index, f"{phase}_attach", start)

        start = time.time_ns()
        self.sync()
        self.wait_for_binding(endpoint["port"])
        self.record_metric(index, f"{phase}_convergence", start)
        return endpoint

    def wait_for_binding(self, port):
        self.runner.wait(
            "ovn-sbctl",
            "--bare",
            "--columns=chassis",
            "find",
            "Port_Binding",
            f"logical_port={port}",
            attempts=max(1, math.ceil(self.timeout / 0.2)),
            interval=0.2,
            until=lambda result: bool(result.stdout.strip("[] \n\t")),
        )

    def sync(self):
        self.runner.run("ovn-nbctl", "--wait=hv", f"--timeout={self.timeout}", "sync")

    def add_service(self, service, backend, protocols):
        endpoint = self.endpoint(backend)
        for protocol in protocols:
            for family, enabled in (
                (4, self.ipv4_enabled),
                (6, self.ipv6_enabled),
            ):
                if not enabled:
                    continue
                name = self.service_name(service, protocol, family)
                self.load_balancers.append(name)
                vip = self.vip(service, family)
                backend_ip = endpoint[f"ipv{family}"]
                if family == 4:
                    vip = f"{vip}:80"
                    backend_ip = f"{backend_ip}:8080"
                else:
                    vip = f"[{vip}]:80"
                    backend_ip = f"[{backend_ip}]:8080"
                self.runner.run(
                    "ovn-nbctl",
                    "--may-exist",
                    "lb-add",
                    name,
                    vip,
                    backend_ip,
                    protocol,
                )
                self.runner.run(
                    "ovn-nbctl",
                    "--may-exist",
                    "ls-lb-add",
                    self.name,
                    name,
                )

    def verify_connectivity(self, index):
        source = self.endpoint(index)
        target_index = (index % len(self.computes) + 1) % len(self.computes)
        target = self.endpoint(target_index)
        start = time.time_ns()
        for family, enabled in (
            (4, self.ipv4_enabled),
            (6, self.ipv6_enabled),
        ):
            if not enabled:
                continue
            destination = target[f"ipv{family}"]
            self.runner.wait(
                "ip",
                "netns",
                "exec",
                source["namespace"],
                "ping",
                "-q",
                "-c",
                "1",
                "-W",
                "1",
                destination,
                guest=source["guest"],
                attempts=self.timeout,
                interval=1,
            )
        self.record_metric(index, "connectivity", start)

    def _remove_endpoint(self, endpoint):
        self.runner.run(
            "bash",
            "-s",
            "--",
            endpoint["namespace"],
            endpoint["interface"],
            guest=endpoint["guest"],
            input=REMOVE_ENDPOINT,
        )

    def cleanup(self):
        if self.cleaned:
            return
        start = time.time_ns()
        first_error = None

        def attempt(*command, **kwargs):
            nonlocal first_error
            try:
                if command:
                    self.runner.run(*command, **kwargs)
                else:
                    kwargs["action"]()
            except Exception as error:
                if first_error is None:
                    first_error = error

        for endpoint in self.endpoints:
            attempt(action=lambda endpoint=endpoint: self._remove_endpoint(endpoint))
        for load_balancer in self.load_balancers:
            attempt("ovn-nbctl", "--if-exists", "lb-del", load_balancer)
        attempt("ovn-nbctl", "--if-exists", "ls-del", self.name)
        for port_group in self.port_groups:
            attempt(
                action=lambda name=port_group: self._destroy_named("Port_Group", name)
            )
        for address_set in self.address_sets:
            attempt(
                action=lambda name=address_set: self._destroy_named("Address_Set", name)
            )
        attempt("ovn-nbctl", "--wait=hv", f"--timeout={self.timeout}", "sync")
        self.cleaned = first_error is None
        self.record_metric("cleanup", "cleanup", start)
        if first_error is not None:
            raise first_error

    def verify_cleanup(self):
        objects = [
            ("Logical_Switch", self.name),
            *(("Load_Balancer", name) for name in self.load_balancers),
            *(("Port_Group", name) for name in self.port_groups),
            *(("Address_Set", name) for name in self.address_sets),
        ]
        for table, name in objects:
            output = self.runner.output(
                "ovn-nbctl",
                "--bare",
                "--columns=name",
                "find",
                table,
                f"name={name}",
            )
            if output:
                raise AssertionError(f"{table} remains after cleanup: {name}")
        for endpoint in self.endpoints:
            self.runner.run(
                "bash",
                "-s",
                "--",
                endpoint["namespace"],
                endpoint["interface"],
                guest=endpoint["guest"],
                input=VERIFY_ENDPOINT_REMOVED,
            )
