# Security policy

Do not report security vulnerabilities in public issues. Contact the
maintainers privately using an address in `README.md` and include a minimal
reproduction, affected version and impact.

QFinZero has no built-in authentication boundary. Operators exposing it to a
network must add authentication, TLS and network access controls. Never commit
market-data credentials, model API keys, access tokens or proprietary datasets.
