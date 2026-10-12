#!/bin/bash
# Build the accessibility helper next to this script.
cd "$(dirname "$0")" && swiftc -O -swift-version 5 axctl.swift -o axctl && echo "built tools/axctl"
