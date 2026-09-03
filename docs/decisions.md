# EventPulse Decisions

Decisions and verified AWS facts this project relies on, recorded as they are
confirmed against official sources. Each entry: status (VERIFIED = matches
plan assumption / DRIFTED = differs / UNVERIFIED = source unreachable),
verification date, source URL, finding, impact.

How to read: when a story depends on one of these facts, re-check the source
URL first if the fact is older than ~6 months. No DRIFTED entry is ever
silently ignored — each carries the downstream action.

---

## Baseline

- **Date:** 2026-08-31
- **Local toolchain:** SAM CLI 1.165.0, boto3 1.43.84, Lambda target runtime
  python3.12, region us-east-1, account 373550663790 (profile
  `eventpulse-admin`, AdministratorAccess).
- **Pipeline direction:** GitHub Actions, official AWS actions (see F1).

---

## F1 — SAM deploy via GitHub Actions

- **Status:** DRIFTED (plan named a community action that no longer exists)
- **Verified:** 2026-08-31
- **Sources:**
  - https://github.com/aws-sam-actions/deploy-cloudformation-stack — **HTTP 404, repo removed**
  - https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/deploying-using-github.html — official example workflow
  - https://github.com/aws-actions/setup-sam/releases — tags v0..v3; v3 current
- **Finding:** The community `aws-sam-actions/deploy-cloudformation-stack@v2`
  action named in the original plan no longer exists (404). AWS's official,
  current pattern is plain `sam build` + `sam deploy` in the job, with the
  AWS-owned actions setting up the environment:
  `actions/checkout`, `actions/setup-python`, `aws-actions/setup-sam@v3`,
  `aws-actions/configure-aws-credentials@v4`, then
  `sam deploy --no-confirm-changeset --no-fail-on-empty-changeset`.
  (The official doc still shows older tags — setup-sam@v2,
  configure-aws-credentials@v1 — but majors track releases.)
- **Decision (ST-19..22):** pipeline uses `aws-actions/setup-sam@v3` +
  `aws-actions/configure-aws-credentials@v4` + `/usr/local path sam build` +
  `sam deploy`. No third-party deploy action.
- **Impact:** ST-19 (test gate), ST-20/21 (dev/prod deploy) already assume
  configure-aws-credentials@v4 — confirmed correct; setup-sam@v3 added;
  community action removed from plan.

---

## F2 — Firehose (Amazon Data Firehose) buffering to S3

- **Status:** VERIFIED
- **Verified:** 2026-08-31
- **Sources:**
  - https://docs.aws.amazon.com/firehose/latest/APIReference/API_BufferingHints.html
  - https://docs.aws.amazon.com/firehose/latest/APIReference/API_CreateDeliveryStream.html
  - https://docs.aws.amazon.com/firehose/latest/dev/buffering.html
- **Finding:** Buffer size range **1–128 MiB**, buffer interval range
  **60–900 s**; the condition hit first triggers delivery. Values are
  *hints* — Firehose may deviate slightly for record boundaries. Default when
  no hint given: **5 MiB or 5 minutes**, whichever first. For dynamic
  partitioning: minimum buffer size 1 MiB; zero buffering not available.
- **Decision (ST-13):** target hints 64 MiB / 60 s — inside the verified
  range; Parquet + GZIP conversion used (enable the Parquet/GZIP destination
  properties when creating the stream).
- **Impact:** ST-13 stream config; cost story (buffered Parquet = fewer, larger
  objects = cheap Athena scans).

---

## F3 — Athena partition projection vs MSCK REPAIR

- **Status:** VERIFIED
- **Verified:** 2026-08-31
- **Sources:**
  - https://docs.aws.amazon.com/athena/latest/ug/partition-projection.html
  - https://docs.aws.amazon.com/athena/latest/ug/partition-projection-setting-up.html
  - https://repost.aws/knowledge-center/athena-new-partition-query
- **Finding:** Partition projection makes Athena compute partition
  values/locations in memory from table properties instead of doing Glue Data
  Catalog metadata lookups, so new partitions are queryable without
  `MSCK REPAIR TABLE` or crawlers. Supported types: `enum`, `integer`,
  `date`, `injected`. `date` supports a `yyyy/MM/dd` format string. The
  `storage.location.template` must match the real S3 directory structure, and
  the `projection.<col>.range` (e.g. `2024-01-01,NOW`) bounds the projected
  range.
- **Decision (ST-16):** Tier A Glue table: `PARTITIONED BY (day DATE)` +
  `projection.enabled=true`, `projection.day.type=date`,
  `projection.day.format=yyyy/MM/dd`, range `2024-01-01,NOW`. No crawlers,
  no MSCK REPAIR — the interview talking point holds.
- **Impact:** ST-16 DDL; ST-17 SQL queries filter on `day` (partition
  pruning) — unchanged.

---

## F4 — Athena pricing

- **Status:** VERIFIED (with noted variance)
- **Verified:** 2026-08-31
- **Sources:**
  - https://aws.amazon.com/athena/pricing/ — examples use **$5 per TB scanned**
  - https://docs.aws.amazon.com/whitepapers/latest/big-data-analytics-options/amazon-athena.html — "$5 per TB of data scanned"
  - 3rd-party (cloudburn.io, cloudcostcutter.cloud) claim: no free tier for
    Athena SQL + general 10 MB minimum per query — **not found on the
    official pricing page**, flagged only.
- **Finding:** Standard per-query pricing is **$5 per TB scanned**
  (example-based on the official page; us-east-1 = $5/TB per whitepaper).
  The official pricing page does **not** advertise a free tier for Athena
  SQL queries this session. The 10 MB-per-query minimum is documented for
  federated-data queries; its general applicability is a third-party claim.
- **Impact:** ST-18 cost notes + ST-25 README cost table: hobby-scale
  (sub-GB scans/month) rounds to ~$0.01/mo — fine under the $5 budget
  alarm. Do not cite a "1 TB free tier" in the README or interview talk
  track unless re-verified; official page shows none.