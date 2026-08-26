# Security policy

## Supported version

Security fixes are applied to the latest tagged release and the default branch.

## Reporting

Do not disclose credentials or a reproducible vulnerability in a public issue. Contact the repository owner privately through the address listed in the GitHub security advisory for this repository.

## Deployment requirements

- replace all example database passwords and `SECRET_KEY` values;
- keep `.env` outside Git;
- use HTTPS and secure cookies in network deployments;
- restrict PostgreSQL and model storage to trusted networks;
- disable demo credentials in institutional deployments;
- configure CORS to the deployed frontend origin;
- back up and test restoration of PostgreSQL;
- treat uploaded datasets and office documents as untrusted input;
- keep optional LLM keys in deployment secrets, never in the browser.

Build progress and generation claims are persisted in PostgreSQL. Before a
multi-worker deployment, run the concurrency contract tests and retain the
unique build-claim constraint; do not replace this coordination mechanism with
process-local memory.

The in-app Git version routes are restricted to the `admin` role. Deployments
must still ensure that the repository directory is readable only by the service
account and that branch creation is not exposed to untrusted users.

Curriculum data may contain institutional or unpublished programme information. Administrators are responsible for retention rules and access control appropriate to their institution.
