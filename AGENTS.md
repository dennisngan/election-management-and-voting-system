# Project agent instructions

## Read by task

- Before domain exploration or implementation, read [domain guidance](docs/agents/domain.md),
  then the relevant requirements and ADRs.
- For implementation, debugging or validation, read [development](docs/agents/development.md).
- For the normal `config.yml` server layout, read [deployment](docs/QUICKSTART.md).
  For the separate `compose.yaml` host-profile layout, read [advanced deployment](docs/DOCKER-DEPLOYMENT.md).
- For backup or restore work, read [backup contracts](docs/BACKUP-RESTORE.md).
- For native builds, client upgrades or source delivery, read [building](docs/BUILDING.md).
- For PDF/font changes, read [report fonts](docs/report-font.md).
  For complaint-category changes, read [reference provenance](docs/reference-complaints.md).

## Local tracker

Track specs and tickets under ignored `.scratch/`. Read [tracker conventions](docs/agents/issue-tracker.md)
when creating or updating them, and [triage labels](docs/agents/triage-labels.md) when setting status.
The committed specification and ADRs remain usable when local tracker files are absent.
