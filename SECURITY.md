# Security Policy

## Supported version

Security fixes are applied to the latest release of `mlops-platform`.

## Reporting a vulnerability

Do not open a public issue containing exploit details, credentials, tokens, or private data.
Use the repository's private security-advisory channel when available. Include the affected
version, reproduction steps, impact, and any suggested mitigation.

## Supply-chain controls

CI validates code and deployment contracts, builds the container as a non-root user, and
blocks releases on critical fixed vulnerabilities found by Trivy. Tagged releases publish
an OCI image to GHCR with BuildKit provenance and SBOM attestations and sign the immutable
image digest with keyless Sigstore Cosign using GitHub OIDC.
