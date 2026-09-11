# Security

Do not commit credentials, delegated tokens, approval codes, tenant documents, or
deployment-generated evidence to this repository.

Use environment variables, Azure Developer CLI environment storage, managed identity,
and Azure resource connections for runtime configuration. Files under
`.foundry/results/`, environment-specific Foundry metadata sidecars, deployment reports,
and environment-specific evaluation summaries are ignored because they can reveal
tenant and resource identifiers.

Report security issues privately through the repository's GitHub Security Advisory
page. Do not open a public issue for a suspected vulnerability or exposed credential.
