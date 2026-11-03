# Gate XAUUSD CFD ABC

Public, read-only Gate CFD market-data collection, quality audit and ABC V1.0 simulation research.
No account trading API, API keys, order placement, or live trading capability.

## Current state

The original acquisition bug has been repaired: `/tradfi/symbols/detail` now requires authentication, so the public `/tradfi/symbols` identity endpoint is used. Native Gate CFD XAUUSD quotes and 4H/1H/15m/1m bars were obtained and audited in an interactive cloud environment. Archived REAL snapshots are regression fixtures, not a fresh live-data approval.

GitHub Actions actually ran on 2026-11-03 at 20:11 Beijing time: run `41633582940`, commit `eacb782ebc28b7218c177a0dba216e9eb9a43b9d`. The native CFD fetch/audit and ABC calculation passed; the report was observation only. All 19 regression tests also passed. This is actual runner evidence, not merely a successful deployment.

The active notification route is a separate ChatGPT cloud task using the connected Gmail account. The GitHub report was submitted to both authorized recipients and Gmail self-delivery was verified during integration testing. QQ inbox delivery and the first natural scheduled cycle remain unverified. No qualified entry is allowed while the macro-event calendar is unverified. Whole-system acceptance remains pending; a green data-only workflow is not whole-system approval.

## Workflow

- A push to implementation/workflow files or manual dispatch runs the official API pipeline once on a standard `ubuntu-latest` runner.
- The hourly cron is minute 03 (also Beijing minute 03). `RUNNER_ENABLED=true` has been configured after integration testing; the next natural trigger still needs verification.
- GitHub fetches/audits/decides and saves evidence. The existing ChatGPT hourly task was upgraded in place to read the same-hour GitHub run and send through connected Gmail at minute 08, Asia/Shanghai. No parallel legacy mail task was created. This route needs no SMTP password and no personal device to remain on, but depends on both cloud schedulers and the Gmail connection.
- `SEND_MAIL` is unset/off on GitHub to prevent duplicate delivery. The SMTP path below is optional and inactive. Do not activate it while the external cloud notifier is active.
- The notifier checks SENT for the exact hourly key before sending, fails closed when the same-hour result is unavailable, records source/notification times and suppresses actionable entries when the quote is over 120 seconds old. At over 15 minutes it reports a notification freshness failure. Delayed notices preserve the original as-of audit state rather than pretending prices are live at send time.
- All decisions are simulations. `approved_for_executable_signal` remains false.

## Optional SMTP fallback: secrets and variables

| Setting | Location | Meaning |
|---|---|---|
| SMTP_USER | Actions Secret | Sender account |
| SMTP_APP_PASSWORD | Actions Secret | SMTP application password, never a chat message or committed file |
| SMTP_HOST | Actions Secret | Optional; defaults to smtp.gmail.com |
| SMTP_PORT | Actions Secret | Optional; defaults to 465 with TLS |
| MAIL_TO | Actions Secret | Exactly the two explicitly authorized recipient addresses, comma-separated |
| SEND_MAIL | Actions variable | true to attempt SMTP; otherwise data-only verification |
| RUNNER_ENABLED | Actions variable | true enables the data cron; configured after integration testing |

Connected ChatGPT Gmail authorization cannot be copied into this standalone worker; the active cloud notification task uses that connection in its own managed environment. The SMTP entries above are needed only if a later migration intentionally replaces that notification task. SMTP delivery receipts and the mail ledger are excluded from public artifacts/logs. Market evidence is public; credentials are not stored in artifacts. The workflow acceptance JSON covers its local SMTP path only, so email_submission=FAIL in a data-only run does not represent the separately tested Gmail notification route.

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
