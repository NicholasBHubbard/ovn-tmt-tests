import ipaddress
import json
import os
from pathlib import Path


def _network(value, index):
    network = ipaddress.ip_network(value)
    address = int(network.network_address) + index * network.num_addresses
    return ipaddress.ip_network((address, network.prefixlen))


def _mac(index):
    if not 0 <= index < 2**32:
        raise ValueError("port index exceeds deterministic MAC address range")
    return "02:0a:" + ":".join(
        f"{index >> shift & 255:02x}" for shift in (24, 16, 8, 0)
    )


def generate(config):
    if config["port_count"] < 0 or config["start_index"] < 0:
        raise ValueError("port count and start index must be non-negative")
    if config["network_index"] < 0:
        raise ValueError("network_index must be non-negative")
    if config["mtu"] < 0:
        raise ValueError("mtu must be non-negative")
    if not config["ipv4"] and not config["ipv6"]:
        raise ValueError("at least one IP family must be enabled")
    if len(config["interface_prefix"]) > 7:
        raise ValueError("interface_prefix must be at most seven characters")
    if not isinstance(config["chassis"], str) or not config["chassis"]:
        raise ValueError("chassis must be a non-empty name")
    if not isinstance(config["ports"], list):
        raise ValueError("ports must be a list")
    for name in ("nbctl", "ovs_vsctl"):
        if not isinstance(config[name], list) or not config[name] or not all(
            isinstance(item, str) and item for item in config[name]
        ):
            raise ValueError(f"{name} must be a non-empty command list")

    result = {
        "owner": f"{config['id']}:{config['chassis']}",
        "nbctl": config["nbctl"],
        "ovs_vsctl": config["ovs_vsctl"],
        "ports": [],
        "southbound": {
            "datapaths": [],
            "ports": [],
            "absent_datapaths": [],
            "absent_ports": [],
        },
    }

    networks = {
        version: _network(config[f"internal_ipv{version}"], config["network_index"])
        for version in (4, 6)
        if config[f"ipv{version}"]
    }
    ports = config["ports"] or [{} for _ in range(config["port_count"])]
    switch = config["switch"] or f"{config['switch_prefix']}-{config['chassis']}"
    for local_index, overrides in enumerate(ports):
        if not isinstance(overrides, dict):
            raise ValueError("explicit ports must be mappings")
        if any(
            local_index + 1 >= network.num_addresses - 2
            for network in networks.values()
        ):
            raise ValueError(f"chassis {config['chassis']} has too many ports")
        index = config["start_index"] + local_index
        mac = overrides.get("mac", _mac(index))
        addresses = overrides.get(
            "addresses",
            " ".join(
                [
                    mac,
                    *(str(network[local_index + 1]) for network in networks.values()),
                ]
            ),
        )
        port = {
            "name": overrides.get("name", f"{config['port_prefix']}-{index}"),
            "interface": overrides.get(
                "interface",
                f"{config['interface_prefix']}{index:08x}",
            ),
            "switch": overrides.get("switch", switch),
            "chassis": config["chassis"],
            "bridge": overrides.get("bridge", config["bridge"]),
            "mac": mac,
            "addresses": addresses,
            "mtu": overrides.get("mtu", config["mtu"]),
        }
        if not all(
            isinstance(port[key], str) and port[key]
            for key in ("name", "interface", "switch", "bridge", "mac", "addresses")
        ):
            raise ValueError("port names and network properties must be non-empty")
        if len(port["interface"]) > 15:
            raise ValueError("interface names must be at most 15 characters")
        if not isinstance(port["mtu"], int) or port["mtu"] < 0:
            raise ValueError("port MTU must be a non-negative integer")
        result["ports"].append(port)

    result["southbound"]["ports"] = [port["name"] for port in result["ports"]]
    return result


def main():
    output = json.dumps(generate(json.loads(os.environ["OVN_SCALE_PORTS_CONFIG"])))
    path = os.environ.get("OVN_SCALE_PORTS_OUTPUT")
    if path:
        Path(path).write_text(output)
    else:
        print(output)


if __name__ == "__main__":
    main()
