Type: research
Status: resolved
Blocked by: 02

## Question

Which exact NSE/BSE public endpoints and response fields can provide filing broadcast time, revision identity, attachment/XBRL, board meetings, announcements and corporate actions, and can a cached incremental ingestion pass stay reliable within the current Render runtime and zero-cost limits?

## Answer

Yes—with an important boundary. A zero-cost, incremental **NSE-first metadata and XBRL ingestion pass is feasible** on the current Render web service. A complete mirror of every exchange PDF or a full-market BSE announcement crawl is not. The public web APIs are undocumented and protected by exchange edge controls, so this can be reliable only when it is cached, schema-validated, retried conservatively and allowed to fail closed. It is appropriate for this personal research app, not a substitute for a licensed commercial feed or permission to redistribute exchange data.

Research and live endpoint checks were performed on 6 September 2026 against the exchange-owned pages, API responses and archive files.

### NSE endpoints and authoritative fields

| Domain | Public endpoint | Fields to preserve |
|---|---|---|
| Corporate announcements | `GET https://www.nseindia.com/api/corporate-announcements?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY` | `seq_id` (external identity), `symbol`, `sm_isin`, `sm_name`, `desc`, `attchmntText`, `an_dt`, `dt`, `sort_date`, `exchdisstime`, `difference`, `attchmntFile`, `attFileSize`, `hasXbrl`, `old_new` and the full raw row. |
| Financial results | `GET https://www.nseindia.com/api/corporates-financial-results?index=equities&period=Quarterly&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY` | `seqNumber`, `symbol`, `isin`, `companyName`, `broadCastDate`, `exchdisstime`, `difference`, `filingDate`, `fromDate`, `toDate`, `financialYear`, `period`, `relatingTo`, `audited`, `consolidated`, `cumulative`, `format`, `oldNewFlag`, `reInd`, `resultDescription`, `resultDetailedDataLink`, `xbrl` and the full raw row. |
| Integrated financial filing | `GET https://www.nseindia.com/api/integrated-filing-results?index=equities&type=Integrated%20Filing-%20Financials&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY&page=N&size=N` | `seq_Id`, `symbol`, `smName`, `qe_Date`, `type`, `type_Sub` (`Original`/`Revision`), `audited`, `consolidated`, `broadcast_Date`, `creation_Date`, `revised_Date`, `revision_Remark`, `pdf_attach`, `xbrl`, `ixbrl`, file sizes, `diff` and the full raw row. The response also supplies `page`, `size` and `totalCount`. |
| Board meetings | `GET https://www.nseindia.com/api/corporate-board-meetings?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY` | `bm_symbol`, `sm_isin`, `sm_name`, `bm_date`, `bm_purpose`, `bm_desc`, `bm_timestamp`, `sysTime`, `diff`, `attachment`, `ixbrl`, `intimationType`, `meetingType`, `oriiginalMeetingDate`, `proposedMeetingDate` and the full raw row. |
| Corporate actions | `GET https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=DD-MM-YYYY&to_date=DD-MM-YYYY` | `symbol`, `isin`, `comp`, `series`, `subject`, `exDate`, `recDate`, `bcStartDate`, `bcEndDate`, `ndStartDate`, `ndEndDate`, `faceVal`, `caBroadcastDate` and the full raw row. `caBroadcastDate` is often null, so the matching corporate announcement supplies the time/source-document evidence. |

NSE’s own page script confirms `/api/integrated-filing-results`, its `type`, date, `period_ended`, `symbol`, `page` and `size` parameters, and its paginated `data`/`totalCount` response. The official pages visibly expose the same attachments, XBRL and exchange received/dissemination timestamps: [announcements](https://www.nseindia.com/companies-listing/corporate-filings-announcements?tabIndex=equity), [financial results](https://www.nseindia.com/companies-listing/corporate-filings-financial-results), and [integrated filings](https://www.nseindia.com/companies-listing/corporate-integrated-filing?tabIndex=equity).

### BSE endpoints and fallback role

| Domain | Public endpoint/page | Fields to preserve |
|---|---|---|
| Corporate announcements | `GET https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=N&strCat=-1&subcategory=-1&strPrevDate=YYYYMMDD&strToDate=YYYYMMDD&strSearch=P&strscrip={optional_code}&strType=C` | `NEWSID`, `BSENewsid`, `SCRIP_CD`, `SLONGNAME`, `NEWSSUB`, `HEADLINE`, `CATEGORYNAME`, `SUBCATNAME`, `DT_TM`, `NEWS_DT`, `News_submission_dt`, `DissemDT`, `TimeDiff`, `ATTACHMENTNAME`, `XML_NAME`, `FILESTATUS`, `CRITICALNEWS`, `QUARTER_ID`, `Fld_Attachsize`, `Investor_Presentation`, `AUDIO_VIDEO_FILE`; `Table1[0].ROWCNT` is the pagination total. Attachment URL is `https://www.bseindia.com/xml-data/corpfiling/AttachLive/{ATTACHMENTNAME}`. |
| Corporate actions | `GET https://api.bseindia.com/BseIndiaAPI/api/DefaultData/w?Fdate=YYYYMMDD&TDate=YYYYMMDD&ddlcategorys=E&ddlindustrys=&segment=0&strSearch=D&scripcode={optional_code}` | `scrip_code`, `short_name`, `long_name`, `Ex_date`, `exdate`, `Purpose`, `RD_Date`, `BCRD_FROM`, `BCRD_TO`, `ND_START_DATE`, `ND_END_DATE`, `payment_date`. |
| Upcoming results | `GET https://api.bseindia.com/BseIndiaAPI/api/Corpforthresults/w?fromdate=YYYYMMDD&todate=YYYYMMDD&scripcode={optional_code}` | `scrip_Code`, `short_name`, `Long_Name`, `meeting_date`, `URL`. Use this as a calendar corroboration, not as proof that a result was filed. |
| Financial-result verification | `https://www.bseindia.com/corporates/Comp_Results.aspx?Code={bse_code}` | The official page exposes financial year, quarter, type, status, `Filing_Date_Time`, `Revised_Date_Time`, `Revision_Reason`, standalone/consolidated XBRL and trend links. It is a human-verification fallback; the app should not depend on scraping this rendered page when the NSE result/XBRL record exists. |
| Board-meeting fallback | [BSE Board Meetings](https://www.bseindia.com/corporates/board_meeting) and `GET https://www.bseindia.com/Data/XML/BoardMeetingsFeed.aspx` | Security, purpose and meeting date. For durable machine ingestion, use the BSE announcement endpoint filtered/matched to board-meeting intimations because it retains filing identity, time and attachment. |

The current `qualitative_engine.py` calls an obsolete parameter form (`Category`, `scrip_cd`, `strdate`, `enddate`, `type`, `offset`). On the live API this now returns `Both From Date and To Date must be provided`. It must be replaced by the current `strCat`, `strPrevDate`, `strToDate`, `strSearch`, `strscrip` and `strType` contract above.

### Measured shape and cost

- NSE announcements returned 699 rows for 4 September 2026 in one request.
- NSE board meetings returned 99 rows for 1–4 September, and corporate actions returned 69.
- Integrated financial filings returned seven rows for 4 September. The endpoint can emit duplicate variants with the same `seq_Id` and different null/file-size fields; merge by external identity and retain the raw variants rather than counting them as separate filings.
- Representative XBRL instances were only about 20 KB and 60 KB, arrived in roughly 34–247 ms from the current host, and contained structured concepts such as `RevenueFromOperations`, `FinanceCosts`, `ProfitBeforeTax` and `ProfitLossForPeriod` with XBRL contexts.
- BSE returned 2,023 announcements for 4 September at 50 rows per page—about 41 requests for a complete market day. That is too wasteful for a daily whole-market fallback. BSE corporate-action and upcoming-result queries returned in roughly 0.1–0.2 seconds in the live check.
- The existing daily pipeline takes roughly five to six minutes and already makes far more expensive all-universe price/fundamental calls. Four or five market-wide NSE metadata requests plus a few small XBRL downloads add seconds, not minutes, when performed incrementally.

### Required ingestion design

1. **NSE is primary for the NSE universe.** Query market-wide exchange metadata by date, never one request per security. Use BSE only to corroborate shortlisted names, recover a missing NSE record, or perform a bounded weekly reconciliation.
2. **Run metadata before scoring.** Query announcements, financial results, integrated filings, board meetings and corporate actions for a seven-calendar-day overlap ending at the completed-session cutoff. Once weekly, reconcile a 35-day window so late revisions are captured.
3. **Append; never overwrite.** Add a raw `exchange_filings` ledger with exchange, domain, external id, ISIN/symbol, received/broadcast/disseminated timestamps, effective/period dates, original/revision relationship, attachment/XBRL URLs, raw payload hash, first/last observation and retrieval status. `seq_id`, `seqNumber`, `seq_Id` and BSE `NEWSID` are the preferred external ids; use a deterministic evidence hash only where the exchange supplies none.
4. **Deduplicate carefully.** Merge integrated rows sharing `seq_Id` while retaining every raw variant. A revision becomes a new immutable record linked to its predecessor. Never identify a revision only by filename or period label.
5. **Download selectively.** Persist URLs and metadata for all new filings. Download/parse XBRL for new result filings and for securities entering the deep-enriched/owned/watched bench. Do not mirror every announcement PDF. Hash any downloaded document and retain parse taxonomy/version and errors.
6. **Parse by concept plus context.** Map local XBRL concept names to the deterministic metric vocabulary, while keeping taxonomy namespace, unit, decimals, context period, consolidated/standalone basis and original raw value. Unknown concepts remain archived; they are not silently coerced.
7. **Prove coverage per run.** Store a coverage manifest for every endpoint: requested window, page count, response count, earliest/latest exchange timestamp, schema fingerprint, duration, retries and completion state. An empty successful response is distinct from a failed request.
8. **Bound network behavior.** Reuse one HTTP client, concurrency at most two, 15-second request timeout, at most three jittered retries for transient errors, response-size limits and a circuit breaker. Validate required fields before committing the coverage manifest.
9. **Keep Postgres authoritative.** Raw metadata, cursors, hashes, parsed metrics and manifests belong in the durable database; Render’s ephemeral disk is only temporary download space.
10. **Fail closed.** If mandatory NSE announcement/result coverage is incomplete or its schema changes, no new candidate may become actionable. The previous valid snapshot may remain viewable with an explicit stale/source warning; the daily operating-standard ticket decides the precise publication thresholds.

### Reliability and cost conclusion

This design stays inside the present ₹0 recurring-cost constraint and comfortably inside the observed Render runtime if it remains incremental and does not mirror PDFs. It materially improves data quality because filing time, revision identity, filing basis and source document become first-class evidence rather than inferred metadata.

It is not as operationally guaranteed as NSE’s licensed feeds. NSE lists the dedicated Corporate Data feed at ₹10.6 lakh domestically and its after-20:00 EOD Corporate Announcement SFTP product at ₹5 lakh per year, which is outside the current constraint: [NSE Paid Corporate Data](https://www.nseindia.com/static/market-data/corporate-data-subscription). The public route therefore needs monitoring and a deliberate “source unavailable” state, not optimistic fallback values.
