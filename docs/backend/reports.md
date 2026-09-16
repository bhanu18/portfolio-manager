# Reports API

Base path: `/reports`

Authentication: **required** — all endpoints require a valid Bearer token (`Authorization: Bearer <token>`).

Data scoping:
- **Admin** users see all trades across all groups.
- **Regular** users only see trades from groups they are a member of.

---

## 1. Asset Valuation

```
GET /reports/valuation/{symbol}/{target_currency}
```

Calculates the current value and profit/loss of a single asset holding, converted into any target currency.

### Path parameters

| Parameter | Type | Description |
|---|---|---|
| `symbol` | string | Asset ticker symbol (e.g. `NVDA`, `AAPL`). Case-insensitive. |
| `target_currency` | string | 3-letter currency code for the report output (e.g. `USD`, `THB`, `EUR`). Case-insensitive. |

### How it works

1. Looks up the asset by symbol.
2. Fetches all trades for that asset, filtered to the user's groups.
3. Computes net quantity (buys − sells) and total cost basis in USD.
4. Determines the asset's native currency via yfinance, falling back to a market-to-currency map if yfinance is unavailable.
5. Converts current value from native currency → USD → target currency using live FX rates from yfinance.
6. Returns valuation and profit/loss in the target currency.

### Currency resolution fallback (when yfinance is unavailable)

| Market | Currency |
|---|---|
| NASDAQ, NYSE | USD |
| SET, THAI | THB |
| TSE | JPY |
| LSE | GBP |
| NSE | INR |
| (default) | USD |

### Response

```json
{
  "symbol": "NVDA",
  "asset_native_currency": "USD",
  "reporting_currency": "THB",
  "current_price": 192.53,
  "holdings": {
    "quantity": 12.5,
    "average_cost_usd": 145.2000
  },
  "valuation": {
    "current_value_native": 2406.6250,
    "current_value_usd": 2406.6250,
    "current_value_in_target_currency": 84231.8750
  },
  "performance": {
    "total_cost_in_target_currency": 62537.5000,
    "profit_loss_in_target_currency": 21694.3750
  }
}
```

### Error responses

| Status | Condition |
|---|---|
| `401` | Missing or invalid token |
| `404` | Asset symbol not found |
| `404` | No trades found for this asset (within user's groups) |
| `200` | Asset found but net quantity is zero — returns `{"message": "No active holdings for this asset."}` |
| `503` | Live FX rate unavailable for native currency → USD conversion |
| `503` | Live FX rate unavailable for USD → target currency conversion |

---

## 2. Portfolio Performance

```
GET /reports/portfolio-performance
```

Comprehensive portfolio analysis across all holdings. Uses FIFO cost basis with historical FX rates at each trade date for accurate return attribution.

### Query parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `base_currency` | string | `USD` | Currency for all reported values. |
| `benchmark_ticker` | string | `SPY` | Ticker to compare portfolio performance against (e.g. `SPY`, `QQQ`). |

### How it works

1. Fetches all relevant trades (scoped to user's groups for non-admins).
2. Groups trades by asset and computes net quantity per asset.
3. Skips assets where net quantity ≤ 0 (fully sold positions).
4. For each active holding:
   - Applies **FIFO** ordering to buy trades to determine remaining quantity.
   - Fetches **historical FX rates** at each buy trade date to compute accurate cost basis in base currency.
   - Fetches **current live FX rates** for current value conversion.
   - Splits total return into **local return** (price movement) and **FX return** (currency movement).
   - Computes **annualized return** using the holding period from earliest purchase date.
5. Computes benchmark return from earliest holding date to today using yfinance.
6. Calculates **alpha** = portfolio return − benchmark return.

### Response

```json
{
  "report_date": "2026-07-01",
  "base_currency": "USD",
  "exchange_rates_current": {
    "USD": 1.0,
    "THB": 0.027451
  },
  "portfolio_summary": {
    "total_cost_basis": 18450.00,
    "total_current_value": 22310.75,
    "total_unrealized_gain_loss": 3860.75,
    "total_unrealized_gain_loss_pct": 20.93,
    "total_dividends_received": 0.00,
    "total_return_with_dividends": 20.93,
    "benchmark_ticker": "SPY",
    "benchmark_return": 14.20,
    "alpha": 6.73,
    "currency_impact_summary": {
      "total_fx_gain_loss": 120.50,
      "total_fx_contribution_pct": 0.65,
      "total_local_contribution_pct": 20.28
    }
  },
  "holdings": [
    {
      "ticker": "NVDA",
      "asset_name": "NVDA",
      "purchase_date": "2025-11-03",
      "original_currency": "USD",
      "purchase_price_original": 145.20,
      "current_price_original": 192.53,
      "quantity": 12.5,
      "fx_rate_at_purchase": 1.0,
      "fx_rate_current": 1.0,
      "cost_basis_original": 1815.00,
      "cost_basis_base": 1815.00,
      "current_value_original": 2406.63,
      "current_value_base": 2406.63,
      "unrealized_gain_loss_base": 591.63,
      "unrealized_gain_loss_pct": 32.60,
      "local_return_pct": 32.60,
      "fx_return_pct": 0.00,
      "total_return_pct": 32.60,
      "holding_period_days": 240,
      "is_long_term": false,
      "annualized_return": 55.23,
      "weight_pct": 10.79,
      "asset_type": "stock"
    }
  ],
  "by_currency": {
    "USD": {
      "value_base": 22310.75,
      "cost_basis_base": 18450.00,
      "weight_pct": 100.00,
      "local_return_pct": 20.28,
      "fx_return_pct": 0.00,
      "total_return_pct": 20.93
    }
  },
  "by_asset_type": {
    "stock": {
      "value_base": 22310.75,
      "cost_basis_base": 18450.00,
      "weight_pct": 100.00
    }
  },
  "top_performers": [
    { "ticker": "NVDA", "total_return_pct": 32.60 }
  ],
  "bottom_performers": [
    { "ticker": "ADBE", "total_return_pct": -5.10 }
  ],
  "fx_warnings": []
}
```

### Response field reference

#### `portfolio_summary`

| Field | Description |
|---|---|
| `total_cost_basis` | Total amount paid for all current holdings, in base currency |
| `total_current_value` | Current market value of all holdings, in base currency |
| `total_unrealized_gain_loss` | `current_value − cost_basis` |
| `total_unrealized_gain_loss_pct` | Percentage gain/loss on cost basis |
| `benchmark_return` | Total return of the benchmark since earliest holding purchase date |
| `alpha` | `portfolio_return − benchmark_return` |
| `currency_impact_summary.total_fx_gain_loss` | Gain/loss attributable purely to FX rate movement |
| `currency_impact_summary.total_fx_contribution_pct` | FX gain as % of cost basis |
| `currency_impact_summary.total_local_contribution_pct` | Price movement gain as % of cost basis |

#### Per holding (`holdings[]`)

| Field | Description |
|---|---|
| `purchase_date` | Date of earliest buy trade (FIFO) |
| `original_currency` | Currency the asset trades in |
| `purchase_price_original` | Weighted average buy price in original currency |
| `current_price_original` | Current market price in original currency |
| `fx_rate_at_purchase` | Weighted avg FX rate (original → base) at time of purchase |
| `fx_rate_current` | Current FX rate (original → base) |
| `cost_basis_base` | Total cost in base currency using historical FX rates |
| `current_value_base` | Current value in base currency using live FX rate |
| `local_return_pct` | Return from price movement only (excludes FX effect) |
| `fx_return_pct` | Return from FX rate change only (excludes price movement) |
| `total_return_pct` | Combined total return in base currency |
| `holding_period_days` | Days since earliest purchase |
| `is_long_term` | `true` if holding period ≥ 365 days |
| `annualized_return` | Return normalized to a yearly rate |
| `weight_pct` | This holding's share of total portfolio value |

#### `by_currency`

Groups holdings by the currency the asset trades in. Shows value, cost basis, portfolio weight, and return split (local vs FX) per currency.

#### `by_asset_type`

Groups holdings by asset type (`stock`, `crypto`, `etf`, `cash`). Shows value, cost basis, and portfolio weight per type.

#### `top_performers` / `bottom_performers`

Up to 5 holdings with the highest and lowest `total_return_pct` respectively.

#### `fx_warnings`

List of warnings (up to 10) where historical FX rates could not be fetched and a fallback was used. Each entry includes `ticker` and a `message` describing the fallback.

### Error responses

| Status | Condition |
|---|---|
| `401` | Missing or invalid token |
