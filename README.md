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

The workflow runs every six hours and can also be started manually from GitHub Actions.
