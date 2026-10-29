# Verified employer expansion — 29 October 2026

Five distinct public employer boards were added without changing collectors,
notification rules, Android code, or the previous 84 source registrations.

| Employer | Coverage evidenced by vacancies | Cards/location records parsed | Relevant unexpired jobs after existing deduplication |
| --- | --- | ---: | ---: |
| HanmiGlobal Saudi | Saudi Arabia | 58 | 1 |
| Advanced Roads and Development | Saudi Arabia | 10 | 1 |
| QSIT | Egypt | 8 | 6 |
| Oceangate | Egypt | 2 | 1 |
| BKF Engineers | Actual Workable vacancy locations | 313 | 1 |

Counts are the results of the bounded live check on this date, not a promise of
daily vacancies. The larger card totals include other professions and/or locations.
Existing keyword, Quantity Surveyor exclusion, 45-day expiry and deduplication rules
remain unchanged. Current job totals can differ on later runs.

Every board was read through the production `Fetcher` with robots and TLS
verification enabled, using an existing parser. A relevant application's public
HTTPS page was also checked for HTTP 200. No challenge bypass, account credentials,
applicant data, application submission or notification was used for the audit.

The source registry now contains 89 registrations, 88 enabled. Search/country
variants of an employer were not counted as new sources. Existing source records
were preserved.

Excluded examples: GAMA's careers host had a TLS hostname mismatch; Nesma's careers
certificate was expired; Geomantix application links were empty; AppLogica GIS
application links were commented out; the tested Hire Resolve/RPO public feeds
contained no vacancies. They were not added merely to increase the source count.

Boskalis was also excluded: its career board groups vacancies by department, which
the existing SmartRecruiters HTML parser would misread as a city. No headquarters
country was substituted, and no shared parser was changed for this expansion.
QSIT's generic consultation-management card was excluded so its six selected roles
all explicitly identify GIS in their titles.

The three HTML selector contracts have small offline regression fixtures in
`jobs/tests/test_verified_source_expansion.py`. Local bounded live evidence is saved
outside the repository as `outputs/jobs-new-source-audit-20261029.json`.
