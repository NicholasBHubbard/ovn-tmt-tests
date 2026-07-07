#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

mkdir -p /etc/openvswitch
cd /etc/openvswitch

openssl genrsa -out ca-privkey.pem 2048 2>/dev/null
openssl req -x509 -new -key ca-privkey.pem -out cacert.pem \
    -days 1 -subj "/CN=Test CA" 2>/dev/null

openssl genrsa -out ovn-privkey.pem 2048 2>/dev/null
openssl req -new -key ovn-privkey.pem -out ovn-req.pem \
    -subj "/CN=OVN" 2>/dev/null
openssl x509 -req -in ovn-req.pem -CA cacert.pem -CAkey ca-privkey.pem \
    -CAcreateserial -out ovn-cert.pem -days 1 2>/dev/null

rm -f ovn-req.pem ca-privkey.pem cacert.srl

assert_file /etc/openvswitch/ovn-privkey.pem
assert_file /etc/openvswitch/ovn-cert.pem
assert_file /etc/openvswitch/cacert.pem
assert_finish
