# Gate XAUUSD CFD ABC

Public, read-only Gate CFD market-data collection, quality audit and ABC V1.0 simulation research.
No account trading API, API keys, order placement, or live trading capability.

## Current state

The original acquisition bug has been repaired: `/tradfi/symbols/detail` now requires authentication, so the public `/tradfi/symbols` identity endpoint is used. Native Gate CFD XAUUSD quotes and 4H/1H/15m/1m bars were obtained and audited in an interactive cloud environment. Archived REAL snapshots are regression fixtures, not a fresh live-data approval.

GitHub Actions deployment and external SMTP acceptance must be verified independently. A green data audit does not certify delivery, profit or complete system acceptance.

## Workflow

- A push to implementation/workflow files or manual dispatch runs the official API pipeline once on a standard `ubuntu-latest` runner.
- The hourly cron is minute 03 (also Beijing minute 03). Until `RUNNER_ENABLED=true`, scheduled production runs remain disabled to preserve the existing notifier during migration.
- Default runs fetch/audit/decide without sending mail. To test independent email, configure the repository Secrets below, set `SEND_MAIL=true`, then manually dispatch. A valid macro-event calendar is also required for S4; without it the system can report observations but never emits a qualified entry.
- After verifying both authorized recipients were accepted, pause the former notifier and set `RUNNER_ENABLED=true`. Do not run two production mail schedulers together.
- All decisions are simulations. `approved_for_executable_signal` remains false.

## Secrets and variables

| Setting | Location | Meaning |
|---|---|---|
| SMTP_USER | Actions Secret | Sender account |
| SMTP_APP_PASSWORD | Actions Secret | SMTP application password, never a chat message or committed file |
| SMTP_HOST | Actions Secret | Optional; defaults to smtp.gmail.com |
| SMTP_PORT | Actions Secret | Optional; defaults to 465 with TLS |
| MAIL_TO | Actions Secret | Exactly the two explicitly authorized recipient addresses, comma-separated |
| SEND_MAIL | Actions variable | true to attempt SMTP; otherwise data-only verification |
| RUNNER_ENABLED | Actions variable | true only after the production migration gate is satisfied |

Connected ChatGPT Gmail authorization cannot be copied into this standalone worker. Secrets must be securely configured by the account owner. SMTP delivery receipts and the mail ledger are excluded from public artifacts/logs. Market evidence is public; credentials are not stored in artifacts.

## Evidence and recovery

`output/http/` contains actual response body, HTTP code, elapsed time, headers and SHA256, including failures. Other outputs: `audit.json`, `decision.json`, closed-bar CSVs, `report.txt`, `run.json`, `error.log` and private `email_delivery.json`.

The workflow publishes only market/audit/decision/timing evidence for seven days. It separately caches the delivery ledger to suppress repeated submissions in the same hourly slot. Ambiguous SMTP submission is marked UNKNOWN and is not blindly retried. Recover the ledger before rerunning mail after cache loss; strict exactly-once delivery is not guaranteed.

Temporary API/connect errors retry at most three times. Authentication and region errors are not bypassed. FAIL blocks simulation signals; normal validated closure is RESTING. Unknown gaps fail closed. See `STRATEGY_MAPPING.md` for causal structure rules, dynamic-zone implementation definitions and inferred public-feed session model.

API response timestamps are not tick timestamps. The latest actual 1m bar and native OHLC cross-checks bound freshness; last-tick time and account-specific 7x23 beta rights remain unverified. No fabricated volume/OI is used. Macro calendar unavailable means no S4. There is no independent missing-run watchdog yet.

Standard hosted runner compute on public repositories is free under GitHub's published policy. Artifact/cache usage still has plan limits; this workflow uses a seven-day retention to limit storage and never purchases resources. GitHub cron may be late or skipped; actual start and nominal minute-03 offset are recorded. A manual/push offset is not a measured scheduling delay.

## Local verification

Python 3.10+ with IANA timezone data, no third-party Python packages:

```sh
python -m unittest -v test_gate_audit.py test_cloud_runner.py
python cloud_runner.py --out-dir output
python cloud_runner.py --out-dir output --state-dir state --send-mail
```

Reference: https://www.gate.com/docs/developers/apiv4/en/cfd/
