Type: prototype
Status: resolved
Blocked by: 01, 03

## Question

What is the smallest daily user workflow that lets the user understand the market environment, inspect at most five actionable candidates, verify bull and bear evidence, reject a trade, and record a paper decision without being distracted by the legacy research terminal?

## Prototype reviewed

- [Interactive daily-decision workflow](../daily-decision-workflow-prototype.html)
- The prototype contains both the current fail-closed “No trade today” state and a clearly fictional eligible-day example.
- Approved daily path: **Today → candidate evidence → Reject / Watch exact trigger / Track on paper**.
- The user explicitly requires stock ranking, not only a top-five list. `Rankings` is therefore a primary destination alongside `Today` and `Paper book`.
- `System` and settings move behind `More`; they do not interrupt the daily path.

## Answer

The app has two deliberately separate stock-selection surfaces:

1. **Rankings** contains the complete session-frozen ordering of every stock that passes the basic qualification screen. It supports search, filtering and sorting; each row exposes score, setup, evidence completeness and decision state. No qualified stock disappears merely because it falls outside the top five.
2. **Today** filters that full ranking through mandatory evidence, event, freshness and trade-geometry gates, then presents zero to five paper-ready or near-trigger decisions. Its limit controls decision overload; it does not limit ranking coverage.

Rank is relative research priority, not predicted return, investment advice or permission to trade. A highly ranked stock can remain research-only or rejected when a required gate fails. The user approved this revised workflow on 2026-09-06.
