#!/usr/bin/env sh
# Creates .env from .env.example with freshly generated local secrets.
# Safe to re-run: an existing .env is never overwritten.
set -eu

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  echo ".env already exists; leaving it unchanged."
  exit 0
fi

random_hex() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    python3 -c 'import secrets; print(secrets.token_hex(32))'
  fi
}

jwt_secret=$(random_hex)
postgres_password=$(random_hex)

# Owner-only from the first byte, not after a later chmod.
umask 077
sed \
  -e "s/^JWT_SECRET=.*/JWT_SECRET=${jwt_secret}/" \
  -e "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=${postgres_password}/" \
  .env.example > .env

echo "Created .env with generated JWT_SECRET and POSTGRES_PASSWORD."
