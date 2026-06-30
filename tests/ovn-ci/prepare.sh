#!/bin/bash
set -euo pipefail

dnf install -y \
    autoconf \
    automake \
    checkpolicy \
    clang \
    curl \
    dhcp-client \
    dhcp-server \
    ethtool \
    gcc \
    gcc-c++ \
    git \
    glibc-langpack-en \
    groff \
    iproute \
    iproute-tc \
    iputils \
    jemalloc-devel \
    kernel-devel \
    kmod \
    libasan-static \
    libcap-ng-devel \
    libtool \
    libubsan-static \
    llvm-devel \
    make \
    net-tools \
    nfdump \
    nftables \
    ninja-build \
    nmap-ncat \
    numactl-devel \
    openssl \
    openssl-devel \
    procps-ng \
    python3-devel \
    python3-pip \
    rpmdevtools \
    rsync \
    selinux-policy-devel \
    tcpdump \
    unbound \
    unbound-devel \
    wget \
    which \
    sparse

mkdir -p /workspace

git clone "${OVN_REPO}" /workspace/ovn \
    --branch "${OVN_BRANCH}" --single-branch --depth 1

cd /workspace/ovn
git submodule update --init --single-branch --depth 1

# Install Python dependencies from the OVN repo
python3 -m pip install --break-system-packages --upgrade pip
python3 -m pip install --break-system-packages wheel
python3 -m pip install --break-system-packages \
    -r utilities/containers/py-requirements.txt
