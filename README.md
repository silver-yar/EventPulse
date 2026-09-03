# EventPulse

Serverless event-ingestion platform: POST events, validate + enrich, land them
in date-partitioned S3, run SQL analytics via Athena. Deployed with SAM + IaC,
driven by a kanban backlog (Jira, seed: `docs/backlog.csv`).

## Status

**In progress** — executed as backlog stories ST-1..ST-26 (see
[`docs/backlog.csv`](docs/backlog.csv) for the full ordered backlog).

## Layout

```
template.yaml          SAM template (stub Lambda today; API+S3 in ST-6)
src/ingest/            Lambda code (stub handler today)
scripts/               Ops scripts (setup_budget.py: $5 monthly cost budget)
docs/backlog.csv       Jira import seed for the kanban backlog
```

## Prerequisites

- AWS CLI configured (profile `eventpulse-admin`, region `us-east-1`)
- AWS SAM CLI (`sam`)

## Local checks

```sh
sam build     # must pass
sam validate  # must pass
```

## TODO / caveats

- 2026 AWS facts verified in ST-4 — see [`docs/decisions.md`](docs/decisions.md).
  One drift found: the community `aws-sam-actions/deploy-cloudformation-stack`
  action is gone (404); pipeline will use official
  `aws-actions/setup-sam@v3` + `configure-aws-credentials@v4` + `sam deploy`.