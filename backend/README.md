asynchronous API for tracking a personal portfolio of financial assets. Built with FastAPI and SQLAlchemy, this API provides endpoints for managing assets and trades, fetches real-time price data, and offers dynamic reporting.

### Batch asset lookup

`POST /assets/batch` accepts `{"ids": [1, 2, 3]}` and returns an array of stored
asset records using one database query. It requires an active signed-in user,
accepts 1–500 positive integer IDs, preserves first-requested order, and omits
missing IDs and duplicates. It does not fetch or refresh external market prices.
The frontend uses this endpoint to resolve missing ticker symbols in group trades;
larger lookups are split into batches of 500, and trades remain visible if lookup fails.
