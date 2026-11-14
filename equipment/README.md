# SurveyOne equipment collection

This independent workflow runs at minutes **07 and 37 each hour (UTC)**. GitHub scheduled
runs can be delayed by GitHub; it is a half-hour schedule, not a hard real-time guarantee.
It updates the existing Firebase external equipment feed consumed by Android and the website.
It does not modify Android, collect personal contacts, send FCM, or change jobs, billing or ads.

## Controls and provenance

- `sources.json` references 32 already-reviewed supplier IDs in 28 countries. It is not a claim
  that every country or every supplier has live offers. Actual successful countries appear in diagnostics.
- Admin → Equipment sources → disable source stops collection/public display. Admin paused,
  archived and draft listings are never auto-published; concurrent revision changes win.
- Country/city are the verified supplier business location, not an invented shipping location.
- Only exact allowed HTTPS hosts and their authorized image hosts are accepted. Redirects and
  robots.txt are checked. No search-result snippets, placeholder photos, or scraped contact data.
- Product-specific structured availability is mandatory. Unknown/error responses do not renew
  verification; sold/out-of-stock items lose only their public projection, retaining admin history.
- Existing source photo reuse policy is respected. Images remain on the original supplier server.
- Prices use verified single-offer values, otherwise show contact/quotation instead of a guessed price.
- URL keys prevent duplicates. Offers become due for verification after 12 hours; each run
  refreshes up to 120 due offers and rotates discovery through suppliers. Supplier failures or
  a growing backlog can delay verification, so old evidence is never presented as a fresh check.
- Verified listings expire after 30 days unless reverified. The existing 14-day freshness gate
  stays intact. Stale public projections are pruned to avoid empty first pages; private records remain.

## Run and inspect

Use the existing repository/environment **FIREBASE_SERVICE_ACCOUNT** secret. Never commit it.
The script validates the project ID `survey-one-f63a5`. No new IAM or public database rules required.

```sh
pip install -r jobs/requirements.txt
npm ci --prefix equipment --ignore-scripts
python -m unittest discover -s equipment/test -p 'test_*.py'
npm test --prefix equipment
node equipment/publish.cjs snapshot --limit 120
python -m equipment.collector
node equipment/publish.cjs publish
```

For initial recovery, `snapshot --limit 1500` checks existing offers in a larger one-time batch.
`GOOGLE_APPLICATION_CREDENTIALS` can reference a credential file outside this repository for local runs.
Generated snapshots, plans and credentials are ignored by Git. Actions uploads `last-run.json`
with counts/errors and no secrets. See **Actions → Update Survey Equipment → Run workflow** for
an immediate run. Disable that workflow to stop the schedule without changing any application.
