#!/bin/bash
set -euo pipefail

ovn-nbctl --bare --columns=_uuid find Logical_Router_Static_Route \
    external_ids:ovn-tmt-tests-id=self-route > /tmp/self-route-moved-id
ovn-nbctl --bare --columns=_uuid find Logical_Switch_Port name=self-localnet \
    > /tmp/self-localnet-moved-id
ovn-nbctl --bare --columns=_uuid find Gateway_Chassis name=self-gateway \
    > /tmp/self-gateway-moved-id
ovn-nbctl --bare --columns=_uuid find NAT \
    external_ids:ovn-tmt-tests-id=self-nat > /tmp/self-nat-moved-id
ovn-nbctl --bare --columns=_uuid find DHCP_Options \
    external_ids:ovn-tmt-tests-id=self-dhcp > /tmp/self-dhcp-moved-id

for path in \
    /tmp/self-route-moved-id \
    /tmp/self-localnet-moved-id \
    /tmp/self-gateway-moved-id \
    /tmp/self-nat-moved-id \
    /tmp/self-dhcp-moved-id; do
    test -s "$path"
done
