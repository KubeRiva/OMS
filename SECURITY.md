# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | ✅ Yes              |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Use GitHub's private vulnerability reporting instead:

**[Report a vulnerability](https://github.com/KubeRiva/OMS/security/advisories/new)**

This keeps the report private between you and the maintainers until a fix is released. Include as much of the following information as possible:

- Type of issue (e.g., SQL injection, authentication bypass, SSRF)
- Full paths of source files related to the issue
- Location of the affected source code (tag, branch, commit, or direct URL)
- Step-by-step instructions to reproduce the issue
- Proof-of-concept or exploit code (if possible)
- Impact of the issue, including how an attacker might exploit it

We will acknowledge receipt within **48 hours** and aim to provide a detailed response within **7 days**, including a timeline for a fix.

## Security Considerations for Self-Hosted Deployments

When running KubeRiva OMS in production:

1. **Rotate all secrets** — generate new values for `SECRET_KEY`, `API_KEY`, `WEBHOOK_SECRET` using `openssl rand -hex 32`. The app refuses to start if defaults are detected in production mode.
2. **Never expose PostgreSQL, MongoDB, Redis, or Elasticsearch ports** publicly — they should only be reachable within your private network or Kubernetes cluster.
3. **Use HTTPS** — terminate TLS at your load balancer or ingress controller; never run the API on plain HTTP in production.
4. **Set `ALLOWED_ORIGINS`** to your exact frontend domain — the default `localhost` values are not safe for production.
5. **Rotate the `ANTHROPIC_API_KEY`** if you use AI_ADAPTIVE sourcing — treat it with the same care as a database password.
6. **Webhook HMAC validation** — KubeRiva signs all outbound webhook payloads with HMAC-SHA256. Ensure your receivers validate the `X-KubeRiva-Signature` header.
7. **Shopify connector** — the Shopify HMAC secret (`SHOPIFY_WEBHOOK_SECRET`) must be rotated when staff members with access to the Shopify Partner Dashboard change.

## Disclosure Policy

We follow coordinated disclosure. Once a fix is available, we will:

1. Release a patched version
2. Publish a GitHub Security Advisory
3. Credit the reporter (unless they prefer to remain anonymous)
