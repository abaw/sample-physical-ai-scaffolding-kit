#!/bin/bash
# Required by physai build (it refuses containers without setup hooks),
# but the fake project needs nothing installed beyond the base image.
set -euo pipefail
echo "fake-converter: no-op setup"
