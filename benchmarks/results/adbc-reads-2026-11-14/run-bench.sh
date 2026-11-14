#!/usr/bin/env bash
# Run the comparison in irispython-dx's client image on the pgwire-bench network.
set -euo pipefail
lab=~/.local/share/irispython-dx/adbc-native
exec docker run --rm --network pgwire-bench --cap-add IPC_LOCK \
  -v "$lab/out-linux-arm64-9762165/lib:/drv:ro" \
  -v ~/ws/intersystems-irispython-dx:/layer:ro \
  -v ~/ws/irispython-dx/dxlab/adbc_native:/h:ro \
  -v ~/ws/iris-pgwire/benchmarks/adbc_native_comparison.py:/b/bench.py:ro \
  -v /tmp/pgwire-bench-results:/results \
  -e PYTHONPATH=/layer -e PYTHONDONTWRITEBYTECODE=1 dxlab-adbc-native-client:1 \
  sh -c 'pip install -q --no-deps adbc-driver-postgresql==1.13.0 2>&1 | grep -v WARNING; pip list 2>/dev/null | grep -i adbc; exec python /b/bench.py "$@"' sh "$@"
