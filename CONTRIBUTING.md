# Contributing

Use Python 3.11+ and a current stable Rust toolchain.

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev,server,pipeline]'
.venv/bin/pytest
PYTHONPATH=infra/pmb .venv/bin/pytest infra/pmb/tests
cd infra/upq && cargo test --workspace --all-targets
```

Build and test the dashboard before changing web-facing routes:

```bash
cd infra/dashboard-web
pnpm install --frozen-lockfile
pnpm build
```

Keep public API changes backward compatible when possible. New service routes
need tests and matching documentation. Do not commit credentials, licensed
market data, generated datasets or experiment outputs.
