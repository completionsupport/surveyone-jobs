# Global employer expansion — 29 October 2026

The registry now has **500 enabled independent employer/job boards**. One previously
disabled registration is retained, so the configuration has 501 entries in total.
The previous 89 registrations are preserved; 412 independently checked boards were
added. Country filters, search terms, locations and pages of a board are not
counted as separate sources. Duplicate employer names/boards were rejected.

Every accepted addition was fetched through the production robots-aware Fetcher
with TLS verification. A real, parsable current employer list was required;
HTTP 200 alone, empty placeholders and fictional test fixtures did not qualify.
Zero matching surveying vacancies is explicitly different from a broken board:
many prospective construction/engineering/land/utility employers currently have
other vacancies only. This is not a claim of 500 daily surveying-job publishers.

The reviewed initial addition contains 179 current field-surveying/geospatial
records. The public collected feed grows from 547 to 726 without replacing the
previous records. Actual employer publication dates are preserved when supplied;
missing dates are not fabricated. Unknown countries remain unknown. Requisition
IDs and office/building labels are not used as cities, and company headquarters
are not substituted for vacancy locations.

## Collection and compatibility

- Existing scheduled workflow remains every two hours.
- Up to 500 sources are considered per run, within the existing 900-second budget;
  round-robin resumes at the next source. A complete cycle can span multiple runs.
- Prospective boards without current relevant jobs normally poll every 12 hours;
  boards with current matches generally poll every two hours, subject to the budget.
- Request/response limits, robots/TLS checks, expiry and deduplication remain bounded.
- Public BambooHR, Personio XML and Recruitee job readers were added. No private
  recruiting or candidate endpoint, authentication bypass or paid scraper is used.
- Workday geography now uses an actual published location/path rather than a
  tenant's requisition-ID bullet. Existing requisition IDs and discovery/notification
  history survive that correction.
- Explicit quantity-surveying typos, cargo/medical inspections and property valuation
  title collisions found during the audit are excluded. Electrical GIS collisions
  are avoided by scoped searches on the affected employers.
- The published Android app and its 4 MiB/10,000-row feed contract are unchanged.
  Publication uses the existing editorial-only Pages workflow; it does not send FCM.
  Existing scheduled, country-targeted notification behavior remains in place.

## Discovery attribution

Employer names and public board identifiers were partly discovered using
[LastRound AI's ATS Company Directory](https://github.com/fyrosofttech/lastroundai-hiring-data/tree/main/ats-directory),
by LastRound AI, under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
The directory was filtered, employer labels normalized, unrelated boards excluded,
and selected public endpoints independently reverified on 29 October 2026. This
does not imply endorsement by the directory authors or the employers.

Additional discovery metadata came from the public
[Deriverge ATS company directory](https://deriverge.com/tools/companies-using-ats/).
The directory's historic counts/countries were not treated as current vacancy
proof or used to replace individual job geography. Each source links to its own
original employer feed/application page.

Detailed live checks, rejected candidates, cached public evidence and the merged
publication report are saved outside this repository under the task's `outputs/`.
