# Administrative jobs feed

Jobs entered by a SurveyOne administrator are stored separately from scraped sources.
The installed Android application's existing `jobs.json` URL remains unchanged.

## Enable after deployment

1. Deploy the `editorialJobsFeed` HTTP function and its required Firestore indexes.
2. Confirm its public GET response is a complete v1 snapshot with `authoritative: true`.
3. In `completionsupport/surveyone-jobs`, add an Actions **repository variable**, not a
   secret, named `SURVEYONE_EDITORIAL_JOBS_FEED_URL`, with the deployed HTTPS endpoint:
   `https://europe-west1-survey-one-f63a5.cloudfunctions.net/editorialJobsFeed`.
4. Run the existing Update Survey Jobs workflow. Scheduled collection remains every
   two hours. Check `editorialFeedStatus: healthy` in the run diagnostics.

Alternatively use `"editorialFeed": {"enabled": true, "url": "https://..."}` in
`jobs/config/sources.json`. The repository variable takes precedence. The feature is
inactive until a valid endpoint is configured; there are no credentials in the feed.

## Lifecycle and delivery

- Each job has a stable `editorial_<32 hex>` ID and increasing revision. An edit saves
  a draft; explicitly publish the reviewed revision. Pause/archive withdraws it.
- The authoritative snapshot replaces all prior editorial jobs; an empty snapshot
  removes them. A disabled, stale, malformed or unavailable snapshot also removes
  cached editorial entries, retaining other sources. This intentionally fails closed
  rather than displaying withdrawn contact details. Removal from the GitHub feed
  takes effect at its next successful collection and deployment. Already cached old
  apps may still show a card; the live details page refuses withdrawn/expired jobs.
- Editorial jobs are excluded from the collector's automatic notification queue.
  The admin dashboard has a separate, explicit Notify action targeting only the
  job's stored country topic, e.g. `survey_jobs_eg`. No global topic is used.
- Notify refuses until the same ID and revision appear in the deployed app feed.
  Run collection first or wait for the scheduled run. One attempt is reserved per
  job; editing or republishing cannot create a second attempt. `ACCEPTED` means FCM
  accepted the request, not that a phone displayed it. Ambiguous failures remain
  `UNKNOWN` and are never retried automatically.

## Compatibility and contact

`applyUrl` always points to `https://surveyone.app/en/job/?id=<id>`, so old app versions
can open a valid HTTPS details page. New optional fields are `origin: "EDITORIAL"`,
`revision`, uppercase `countryCode`, `contactName`, `phoneE164`, `allowCall`,
`allowWhatsApp`, and `externalApplyUrl`. WhatsApp is never inferred from the presence
of a phone number. The phone must be E.164; direct contact flags must be explicitly
enabled. An external application link must use public HTTPS.

## Offline tests

`python -m unittest discover -s jobs/tests -v`

Tests use temporary output and fake fetchers. They do not publish data, call FCM or
make requests to the live editorial endpoint.
