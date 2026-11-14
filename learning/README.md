# SurveyOne Learning

Public educational references, separate from jobs and equipment. Videos remain on their
creator's channel and play in SurveyOne through the official YouTube embed.

- `sources.json`: approved channel IDs, language, topic and optional `enabled: false`.
- `curated.json`: manually selected bilingual lessons and official text guides.
- `python -m learning.collector`: discover RSS lessons, filter educational titles,
  verify oEmbed availability, deduplicate and publish `public/learning/catalog.json`.
- `python -m unittest discover -s learning/tests -v`: offline tests.
- `Update Survey Learning`: every six hours or manually. GitHub schedules can be delayed.
- Public URL: https://completionsupport.github.io/surveyone-jobs/learning/catalog.json

No API key, Firebase credentials, paid translation or video hosting is needed. Thumbnails
and embeds retain their original attribution. Discovery keeps original titles; it does
not pretend to translate or dub the source. Unavailable videos are removed; transient
verification failures retain previously verified records for at most seven days. Disabling
a channel removes its discovered lessons at the next run (curated entries are separate).
The app keeps a validated last-good feed for offline browsing. Watching videos needs internet.
The workflow sends no notifications and does not modify Android, jobs, equipment or billing.
