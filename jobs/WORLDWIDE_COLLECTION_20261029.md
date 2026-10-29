# Worldwide collection — 29 October 2026

The reviewed publication has **2,650 active unique source vacancies in 85 known
countries**, up from 726 (net +1,924). There are 1,960 new identities; 224 matching
existing identities retain their original ID and first-discovery time while
receiving refreshed factual metadata. Thirty-six expired or explicitly unrelated
inspection, valuation or scholarship records are withdrawn. These figures exclude
separately paginated community posts and are not a claim of 10,000 vacancies.

The registry has **503 enabled independent boards**: the previous 500 plus official
Swedish JobTech, France Travail and Canadian Job Bank. Thirty existing employer
searches were expanded; GIS Career Hub was expanded from Egypt/Saudi filters to
verified public worldwide queries. Countries, search terms and pages remain parts
of the same board and are never counted as new sources. Prospective employer boards
can be healthy with no current relevant vacancies; this is not a daily-volume promise.

## Evidence and data quality

- GIS Career Hub: 161 actually read, pre-limit public pages and 2,194 distinct
  cards produced 1,784 unique unexpired title-matched jobs after validation.
  Forty-five country/state conflicts, 67 expired cards, unrelated titles and
  post-rate-limit evidence are held. The provider's reported total is not used
  as a collected-vacancy count. Public card attribution is retained, with the
  original HTTPS employer application URL used for cross-source deduplication.
- Official government cards reproduce 155 reviewed current identities: Sweden
  37, France 107, Canada 11. Swedish numeric country taxonomy 199 is not ISO.
  French overseas departments keep their actual territory. Relative French
  publication labels stay explicitly undated; source dates are not refreshed.
  Canadian employer-direct Atom feeds and three public native-card bootstraps
  are required; third-party partner reposts are excluded.
- Thirty expanded existing employer boards supplied 254 current relevant records
  before cross-source/baseline deduplication. Older undated-closing employer rows
  remain held rather than receiving invented deadlines or new posting dates.
- The Swedish JobSearch API is public, CC0 and requires no API key:
  <https://data.jobtechdev.se/dataservice/jobsearch/>.
- Discovery-only TrueNorth/Freehire/Adzuna metadata was not bulk republished:
  commercial API terms or per-ad attribution requirements were incompatible with
  this unchanged Android client. Blocked/robots-disallowed services were not used.

## Collection and Android compatibility

The existing two-hour scheduled workflow, 900-second run budget, country-targeted
FCM policy and Android application are unchanged. Large boards opt into resumable
unread-page queues, bounded per-source requests and host validation. A soft HTTP200
rate-limit page is an error, not a healthy empty list. Query page repetition/caps
are detected. There is no same-run retry of an access/rate-limit denial.

Known ATS requisition aliases and ISO/name country aliases are deduplicated while
retaining distinct countries and distinct roles on shared application forms.
Semantic comparison is bucketed by company/title/country/city instead of scanning
every unrelated job. Explicit relevance exclusions also apply to cached source
rows; editorial authoring and identity remain separate.

The shipped client accepts at most **10,000 rows and 4 MiB**, including its escaped
on-device cache envelope. The reviewed feed is 3,278,135 wire bytes and has a
conservative 3,538,854-byte cache estimate. The publication helper validates both
limits before touching files, can compact whitespace losslessly, and never silently
drops records or shortens their content to fit. Ten thousand detailed real jobs
have not been collected or proven to fit this client. Reaching that target may
require additional permitted live supply and a future paginated-client design.

The reviewed data is published using the existing **editorial-only Pages workflow**:
no manual FCM, payment, permission, Android code, APK, AAB or signing changes.
Normal scheduled collection/notification behavior continues independently.

Offline parser, cached-filter, resumable-pagination, canonical-deduplication and
feed/cache-boundary tests are part of `jobs/tests`. Detailed actual page receipts,
held records, original metadata and independent readback evidence are retained
outside this public repository in the task's local `outputs/` directory.
