import json


class Network:
    def __init__(self, runner, guest=None):
        self.runner = runner
        self.guest = guest

    def namespace_exists(self, namespace):
        result = self.runner.namespace(namespace, "true", guest=self.guest, check=False)
        return result.returncode == 0

    def link(self, interface, namespace=None):
        command = ["ip", "-j"]
        if namespace:
            command.extend(("-n", namespace))
        command.extend(("link", "show", "dev", interface))
        result = self.runner.run(*command, guest=self.guest, check=False)
        if result.returncode:
            return None
        links = json.loads(result.stdout)
        return links[0] if links else None

    def addresses(self, interface, namespace=None, scope=None):
        command = ["ip", "-j"]
        if namespace:
            command.extend(("-n", namespace))
        command.extend(("address", "show", "dev", interface))
        links = json.loads(self.runner.output(*command, guest=self.guest))
        return [
            f"{address['local']}/{address['prefixlen']}"
            for link in links
            for address in link.get("addr_info", [])
            if scope is None or address.get("scope") == scope
        ]

    def routes(
        self,
        namespace=None,
        family=None,
        table=None,
        destination=None,
    ):
        command = ["ip", "-j"]
        if namespace:
            command.extend(("-n", namespace))
        if family:
            command.append(f"-{family}")
        command.extend(("route", "show"))
        if table is not None:
            command.extend(("table", str(table)))
        if destination is not None:
            command.append(destination)
        result = self.runner.run(
            *command,
            guest=self.guest,
            check=False,
        )
        if result.returncode and "FIB table does not exist" not in result.stderr:
            result.check_returncode()
        return json.loads(result.stdout)
