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

The current build-progress registry is process-local. Use one backend worker
until progress and locking are persisted in PostgreSQL or Redis; multiple
workers can otherwise report inconsistent generation status.

Curriculum data may contain institutional or unpublished programme information. Administrators are responsible for retention rules and access control appropriate to their institution.
