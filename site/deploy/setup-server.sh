#!/bin/bash
# One-time setup on the Hetzner box, run from this machine. Idempotent.
set -euo pipefail
ssh httpserver@hetzner bash -s <<'REMOTE'
set -euo pipefail
NAME=notslowapi.com
if [ ! -d ~/private/$NAME.git ]; then git init -q --bare ~/private/$NAME.git; fi
command -v ~/.local/bin/uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
mkdir -p ~/private/$NAME
REMOTE
scp -q site/deploy/post-receive httpserver@hetzner:private/notslowapi.com.git/hooks/post-receive
ssh httpserver@hetzner 'chmod +x ~/private/notslowapi.com.git/hooks/post-receive && ~/.local/bin/uv --version'
echo "next: git remote add production httpserver@hetzner:private/notslowapi.com.git && git push production master"
echo "then: append site/deploy/Caddyfile.snippet to /etc/caddy/Caddyfile (ssh hetzner sudo -n), reload caddy, and ncp dns add notslowapi.com A @ 135.181.216.54 plus www"
