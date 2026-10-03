# Pipeline check (2026-10-02)

- Starter notebook executed end to end on `cfo_appointment` (not an H1/H2 tag), MAX_EVENTS=8, placebo off.
- Endpoints reached with the team key: 8-K disclosures, disclosure taxonomy, options contracts, option daily aggregates, option quotes (`/v3/quotes/{optionTicker}`).
- No H1/H2 event, price or result was fetched or viewed.
- Disclosure (HYPOTHESIS.md section 8, change log 2026-10-02): the starter's out-of-sample cell also ran during this check, on `cfo_appointment` for 2026-01..08 at about 23:00-23:06 ET. It is not an H1/H2 tag, so there is no contamination of the confirmatory study.
