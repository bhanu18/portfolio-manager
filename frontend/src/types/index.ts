// ---------------------------------------------------------------------------
// Shared domain types mirroring the Portfolio Management API response shapes.
// ---------------------------------------------------------------------------

export type UserRole = "user" | "admin";
export type GroupMemberRoleValue = "member" | "group_admin";

export interface Group {
  id: number;
  name: string;
}

// Group entry as seen on the user profile — includes the user's role in that group.
export interface GroupAssociation {
  id: number;
  name: string;
  role: GroupMemberRoleValue;
}

// Normalized user used throughout the app. `groups` is always a flat
// GroupAssociation[] (see normalizeGroups in src/api/auth.ts).
export interface User {
  id: number;
  name: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  groups: GroupAssociation[];
  created_at?: string;
  updated_at?: string;
}

// ---------------------------------------------------------------------------
// Raw `/users/me` shape. The backend exposes a user's groups via a
// many-to-many association, so the serialized payload may present them as
// association/membership objects (each wrapping the actual group) rather than
// a flat list, and the field name itself can vary. We accept all the common
// variants and normalize them to `User.groups`.
// ---------------------------------------------------------------------------

export interface RawGroupAssociation {
  // Direct flat group: { id, name }
  id?: number;
  name?: string;
  // Association columns: { group_id, group_name, role } — actual backend shape
  group_id?: number;
  group_name?: string;
  role?: GroupMemberRoleValue;
  // Nested group on an association/membership row: { group: { id, name } }
  group?: { id?: number; name?: string } | null;
}

export interface RawUser {
  id: number;
  name: string;
  email: string;
  role?: UserRole;
  is_active?: boolean;
  groups?: RawGroupAssociation[] | null;
  group_associations?: RawGroupAssociation[] | null;
  memberships?: RawGroupAssociation[] | null;
  user_groups?: RawGroupAssociation[] | null;
  created_at?: string;
  updated_at?: string;
}

// --- Auth -----------------------------------------------------------------

export interface LoginResponse {
  access_token: string;
  token_type: string; // "bearer"
}

export interface RegisterPayload {
  name: string;
  email: string;
  password: string;
}

export interface ChangePasswordPayload {
  current_password: string;
  new_password: string;
}

export interface ForgotPasswordPayload {
  email: string;
}

export interface ResetPasswordPayload {
  token: string;
  new_password: string;
}

// --- Assets ---------------------------------------------------------------

export type AssetType = "stock" | "crypto" | "cash" | "etf";

export interface Asset {
  id: number;
  symbol: string;
  name: string;
  market: string;
  type: AssetType;
  current_price: number | null;
  price_last_updated: string | null; // ISO datetime
  created_at: string;
  updated_at: string;
  total_quantity?: number | null; // net position across all trades
}

export interface AssetCreatePayload {
  symbol: string;
  name: string;
  market: string;
  type: AssetType;
}

// `type` is required by the backend's AssetUpdate schema even on partial
// updates, so callers must always send the (possibly unchanged) type.
export interface AssetUpdatePayload {
  type: AssetType;
  symbol?: string;
  name?: string;
  market?: string;
  currency?: string;
}

export interface UpdateAllPricesResult {
  message: string;
  updated_count: number;
  skipped_count: number;
  updated_symbols: string[];
  skipped_symbols: string[];
}

// The /assets/{symbol} endpoint returns a plain { error } dict (HTTP 200)
// when the asset is not found, instead of raising. Model that union.
export type AssetBySymbolResult = Asset | { error: string };

// --- Trades ---------------------------------------------------------------

export type TradeType = "buy" | "sell";

// Shape returned by GET /trades/in-group/{group_id} (normalized).
// `symbol` is populated when the backend embeds the related asset, so the UI
// can label the trade without a follow-up asset lookup.
export interface Trade {
  id: number;
  asset_id: number;
  symbol?: string;
  trade_type: TradeType;
  trade_date: string; // ISO datetime
  quantity: number;
  price_per_unit: number;
  currency: string;
  group_id: number;
}

// ---------------------------------------------------------------------------
// Raw trade shape. Like the user/groups payload, the backend may embed the
// related asset as a nested object or expose its symbol directly instead of a
// bare `asset_id`. We accept the common variants and normalize to `Trade`.
// ---------------------------------------------------------------------------

export interface RawTrade {
  id: number;
  // Bare foreign key (documented shape) and common alternatives.
  asset_id?: number;
  assetId?: number;
  // Inline symbol / name variants the backend may return.
  symbol?: string;
  asset_symbol?: string;
  // The actual backend field: "asset_name" carries the ticker symbol string.
  asset_name?: string;
  // Nested asset object on the trade row.
  asset?: { id?: number; symbol?: string; name?: string } | null;
  trade_type: TradeType;
  trade_date: string;
  quantity: number;
  price_per_unit: number;
  currency: string;
  // group_id may be absent when the backend returns group_name instead.
  group_id?: number;
  group_name?: string;
  // Who created this trade — used for edit/delete permission checks.
  created_by_user_id?: number | null;
  created_by_user_name?: string | null; // optional, for display
}

// Shape returned by GET /trades/symbol/{symbol} — note this swaps
// asset_id/currency/group_id for a `symbol` string. Kept distinct on purpose.
export interface TradeResponse {
  id: number;
  symbol: string;
  trade_type: TradeType;
  trade_date: string;
  quantity: number;
  price_per_unit: number;
  currency?: string; // e.g. "USD", "THB" — present on GET /trades/symbol/{symbol}
  group_name?: string;
  group_id?: number; // may be present — needed for group_admin permission check
  // Who created this trade — used for edit/delete permission checks.
  created_by_user_id?: number | null;
  created_by_user_name?: string | null; // optional, for display
}

export interface TradeCreatePayload {
  trade_type: TradeType;
  trade_date: string;
  quantity: number;
  price_per_unit: number;
  currency: string;
  group_id: number;
}

// All fields optional on update.
export interface TradeUpdatePayload {
  trade_type?: TradeType;
  trade_date?: string;
  quantity?: number;
  price_per_unit?: number;
  currency?: string;
  group_id?: number;
}

// --- Groups (v2) -----------------------------------------------------------

export type GroupMemberRole = "member" | "group_admin";

// A single member of a group as returned by GET /groups/{group_id}.
// Note: the backend strips the role field from the members list — only
// id/name/email are available. Role-gating is done via global User.role.
export interface UserInGroup {
  id: number;
  name: string;
  email: string;
}

// Full group detail (GET /groups/{group_id}).
export interface GroupWithMembers {
  id: number;
  name: string;
  members: UserInGroup[];
}

// --- Reports (v2) ----------------------------------------------------------

export interface ValuationReport {
  symbol: string;
  asset_native_currency: string;
  reporting_currency: string;
  holdings: {
    quantity: number;
    average_cost_usd: number;
  };
  valuation: {
    current_value_native: number;
    current_value_usd: number;
    current_value_in_target_currency: number;
  };
  performance: {
    total_cost_in_target_currency: number;
    profit_loss_in_target_currency: number;
  };
}

export interface HoldingAnalysis {
  ticker: string;
  asset_name: string;
  purchase_date: string | null;
  original_currency: string;
  purchase_price_original: number;
  current_price_original: number;
  quantity: number;
  fx_rate_at_purchase: number;
  fx_rate_current: number;
  cost_basis_original: number;
  cost_basis_base: number;
  current_value_original: number;
  current_value_base: number;
  unrealized_gain_loss_base: number;
  unrealized_gain_loss_pct: number;
  local_return_pct: number;
  fx_return_pct: number;
  total_return_pct: number;
  holding_period_days: number;
  is_long_term: boolean;
  annualized_return: number;
  weight_pct: number;
  asset_type: string;
  score?: Score;
}

export interface CurrencyBreakdown {
  value_base: number;
  cost_basis_base: number;
  weight_pct: number;
  local_return_pct: number;
  fx_return_pct: number;
  total_return_pct: number;
}

export interface AssetTypeBreakdown {
  value_base: number;
  cost_basis_base: number;
  weight_pct: number;
}

// --- Scoring (new fields for portfolio performance) ---

export type GradeValue = "A" | "B" | "C" | "D" | "F";

export interface ScoreMetrics {
  cagr: number | null;
  volatility: number | null;
  sharpe: number | null;
  sortino: number | null;
  max_drawdown: number | null;
  beta: number | null;
  alpha: number | null;
}

export interface Score {
  ticker: string;
  metrics: ScoreMetrics;
  subscores: Record<string, number | null>;
  composite_score: number | null;
  weights_used: Record<string, number>;
  grade: GradeValue | null;
  sample_days: number;
  insufficient_history: boolean;
  short_history: boolean;
}

export interface ScoringWarning {
  ticker: string | null;
  message: string;
}

export interface PortfolioPerformanceReport {
  report_date: string;
  base_currency: string;
  exchange_rates_current: Record<string, number>;
  portfolio_summary: {
    total_cost_basis: number;
    total_current_value: number;
    total_unrealized_gain_loss: number;
    total_unrealized_gain_loss_pct: number;
    total_dividends_received: number;
    total_return_with_dividends: number;
    benchmark_ticker: string;
    benchmark_return: number;
    alpha: number;
    currency_impact_summary: {
      total_fx_gain_loss: number;
      total_fx_contribution_pct: number;
      total_local_contribution_pct: number;
    };
  };
  holdings: (HoldingAnalysis & { score?: Score })[];
  by_currency: Record<string, CurrencyBreakdown>;
  by_asset_type: Record<string, AssetTypeBreakdown>;
  top_performers: { ticker: string; total_return_pct: number }[];
  bottom_performers: { ticker: string; total_return_pct: number }[];
  fx_warnings: { ticker: string; message: string }[];
  portfolio_score?: Score | null;
  scoring_warnings?: ScoringWarning[];
}
