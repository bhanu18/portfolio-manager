#!/usr/bin/env bash
# SessionStart hook for Claude Code cloud sessions (wired up in .claude/settings.json).
# Cloud VMs ship PostgreSQL but not MySQL: start MariaDB, create the dev + test DBs,
# install backend (Python 3.12) and frontend deps, and run migrations.
# No-ops anywhere else (e.g. a local Mac).
[ "$CLAUDE_CODE_REMOTE" = "true" ] || exit 0
set -euo pipefail

ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"

# ---- Database ----
if ! mysqladmin -uroot ping >/dev/null 2>&1; then
  service mariadb start || (mysqld_safe --user=mysql >/dev/null 2>&1 &)
  for _ in $(seq 1 30); do
    mysqladmin -uroot ping >/dev/null 2>&1 && break
    sleep 1
  done
fi
# Same throwaway credentials as CI (.github/workflows/ci.yml); local VM only.
mysql -uroot <<'SQL'
CREATE DATABASE IF NOT EXISTS portfolio;
CREATE DATABASE IF NOT EXISTS portfolio_test;
CREATE USER IF NOT EXISTS 'ci'@'localhost' IDENTIFIED BY 'ci';
CREATE USER IF NOT EXISTS 'ci'@'127.0.0.1' IDENTIFIED BY 'ci';
GRANT ALL ON portfolio.* TO 'ci'@'localhost', 'ci'@'127.0.0.1';
GRANT ALL ON portfolio_test.* TO 'ci'@'localhost', 'ci'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL

# Settings need these; only provide them when there is no backend/.env.
if [ ! -f "$ROOT/backend/.env" ]; then
  export DATABASE_URL="mysql+aiomysql://ci:ci@127.0.0.1:3306/portfolio"
  export SYNC_DATABASE_URL="mysql+pymysql://ci:ci@127.0.0.1:3306/portfolio"
  export TEST_DATABASE_URL="mysql+aiomysql://ci:ci@127.0.0.1:3306/portfolio_test"
  export SECRET_KEY="cloud-session-only-not-a-secret-just-long-enough"
  if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
    for var in DATABASE_URL SYNC_DATABASE_URL TEST_DATABASE_URL SECRET_KEY; do
      echo "export $var=\"${!var}\"" >>"$CLAUDE_ENV_FILE"
    done
  fi
fi

# ---- Backend ----
cd "$ROOT/backend"
[ -x venv/bin/python ] || uv venv venv --python 3.12
VIRTUAL_ENV=venv uv pip install -q -r requirements-dev.txt
venv/bin/alembic upgrade head

# ---- Frontend ----
cd "$ROOT/frontend"
[ -d node_modules ] || npm ci --no-audit --no-fund
