# SurveyOne Jobs

Public, privacy-conscious job feed for the SurveyOne Android app.

The scheduled GitHub Action reads a small allowlist of public company career feeds,
respects `robots.txt`, filters surveying/geospatial roles, removes duplicates, expires
old listings, publishes `public/jobs/jobs.json` through GitHub Pages, and can send one
aggregated Firebase Cloud Messaging notification when new jobs are found.

## Public feed

`https://completionsupport.github.io/surveyone-jobs/jobs/jobs.json`

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r jobs/requirements.txt
python -m unittest discover -s jobs/tests -v
python -m jobs.collector.main
```

## Firebase notification secret

Notifications are optional. Add the complete Firebase service-account JSON as the
GitHub Actions repository secret `FIREBASE_SERVICE_ACCOUNT`. Never commit the JSON,
private key, tokens, or downloaded credentials.

The workflow still collects and publishes jobs when this secret is absent; only FCM
delivery is skipped.

## Source policy

- Only sources explicitly listed in `jobs/config/sources.json` are accessed.
- LinkedIn and Indeed are rejected by code.
- Hosts, HTTPS, response size, request count, redirects, and public IPs are validated.
- A source failure retains the last valid feed instead of deleting active jobs.
- Job applications always open the original employer/ATS URL.

## Schedule

The workflow is scheduled every two hours (`17 */2 * * *`) and can also be started
manually from GitHub Actions. GitHub may delay scheduled runs; this is not an
exact two-hour delivery guarantee.

## Verified source coverage

As of 2026-10-04, 68 distinct enabled career boards passed live parsing and clean
collection with zero source failures. The clean isolated collection produced 511 active,
deduplicated jobs across 28 known countries. Current target-country coverage includes
the United Arab Emirates (60), Saudi Arabia (28), the Philippines (12), Kenya (7), Egypt
(6), Pakistan (6), Nigeria (2), and South Africa (1). Official sources added for this
expansion include IRTH, Rise Geo, Stantec, GHD, Punjab Land Records Authority, Fosad,
Kenya National Highways Authority, Orbital Africa, GeoDev Kenya, Hassan Allam, Pakistan's
National Job Portal, Karachi Water and Sewerage Corporation, ACCIONA, SLR Consulting,
World Food Programme, Ferrovial, Westgold, Planet, and BlackSky.
Coverage also includes official Workday, Workable, SmartRecruiters, Oracle Recruiting,
iCIMS, Greenhouse and Lever employer boards. Boards with no current matching jobs remain
useful monitored sources, not fabricated jobs. Country filters and pagination are never
counted as additional sources.

The collector uses a persisted round-robin cursor and bounded time/source budgets.
Malformed feeds and missing endpoints are failures, not healthy empty sources.
Run `python -m jobs.audit_sources --output source-audit.json` for a read-only audit.
Run `python -m jobs.collector.main --output-root .tmp/isolated-collection` to test
collection without changing the production feed, pending jobs, or notification history.

## Country notifications and device verification

Production notifications are grouped by job country and sent only to
`survey_jobs_<country-code>`; jobs with unknown country are not broadcast globally.
Delivery attempts are reserved before sending to avoid duplicate notifications.
Ambiguous failures are not retried automatically; inspect the redacted diagnostic
artifact. FCM acceptance is not proof of receipt on a device.

The manual **Test Survey Jobs on isolated debug phone** workflow accepts only
`surveyone_jobs_qa_<32 lowercase hexadecimal characters>` from the Android debug
device test. It sends a real, unexpired job from the chosen country to that topic
only, without changing production pending/notified state. Use the Android test's
prepare, receipt verification, then cleanup methods. It uses the existing
`FIREBASE_SERVICE_ACCOUNT` secret; no additional secret or device token is needed.
The test topic is not an authentication credential.
