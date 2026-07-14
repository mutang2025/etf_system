export interface ETF {
  id?: number;
  code: string;
  name: string;
  exchange: string;
  etf_type: string;
  track_index?: string;
  theme?: string;
  list_date?: string;
  avg_amount_20d: number;
  total_market_cap: number;
  status: string;
  data_status: string;
  synced_date?: string;
}

export interface KlineData {
  etf_code: string;
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number;
}

export interface RealtimeQuote {
  code: string;
  name: string;
  price: number;
  change_pct: number;
  volume: number;
  amount: number;
  open: number;
  high: number;
  low: number;
  prev_close: number;
  timestamp: string;
}

export interface FactorScore {
  factor_name: string;
  raw_value: number;
  z_score: number;
  weight: number;
}

export interface ScreeningResult {
  etf_code: string;
  etf_name: string;
  layer1_passed: boolean;
  layer2_score: number;
  layer2_rank: number;
  factor_scores: FactorScore[];
  layer3_theme?: string;
  layer3_theme_rank: number;
  layer3_passed: boolean;
  layer4_death_cross: boolean;
  layer4_vol_price_div: boolean;
  layer4_adx_danger: boolean;
  layer4_bb_risk: boolean;
  layer4_passed: boolean;
  final_recommended: boolean;
}

export interface ScreeningSummary {
  select_date: string;
  layer1_passed: number;
  layer2_scored: number;
  layer3_clustered: number;
  layer4_passed: number;
  final_recommended: number;
  funnel: {
    pool_total: number;
    layer1: number;
    layer2: number;
    layer3: number;
    layer4: number;
    final: number;
  };
}

export interface BuySignal {
  signal_id: string;
  signal_type: string;
  etf_code: string;
  etf_name: string;
  trigger_time: string;
  trigger_details: any;
  price: number;
  change_pct: number;
  suggested_amount: number;
  factor_summary: any;
  sell_strategy?: string;
  sell_priority?: number;
  sell_action?: string;
  pnl_amount?: number;
  pnl_pct?: number;
  status: string;
}

export interface Position {
  id?: number;
  etf_code: string;
  etf_name: string;
  buy_signal_id?: string;
  buy_date: string;
  buy_price: number;
  buy_amount: number;
  buy_shares: number;
  current_price: number;
  current_value: number;
  pnl_amount: number;
  pnl_pct: number;
  hold_days: number;
  is_trend_stock: number;
  status: string;
  sell_date?: string;
  sell_price?: number;
  sell_pnl_amount?: number;
  sell_pnl_pct?: number;
  sell_strategy?: string;
}

export interface PortfolioSummary {
  total_positions: number;
  total_value: number;
  total_cost: number;
  total_pnl: number;
  total_pnl_pct: number;
  total_capital: number;
  available_capital: number;
  position_ratio: number;
  trend_stocks: number;
  positions: Position[];
}

export interface PerformanceStats {
  total_trades: number;
  win_count: number;
  loss_count: number;
  win_rate: number;
  total_pnl: number;
  avg_profit: number;
  avg_loss: number;
  profit_loss_ratio: number;
  max_profit: number;
  max_loss: number;
  max_consecutive_losses: number;
}

export interface MonthlyStat {
  month: string;
  trades: number;
  wins: number;
  pnl: number;
  win_rate: number;
}

export interface StrategyParam {
  param_key: string;
  param_value: string;
  param_group: string;
  description: string;
}

export interface DashboardData {
  portfolio: PortfolioSummary;
  signals: {
    buy_count: number;
    sell_count: number;
    recent: any[];
  };
  market: {
    hs300_change: number;
    is_empty_signal: boolean;
    empty_reason: string;
    is_trading_day: boolean;
  };
  performance: PerformanceStats;
  pool: {
    total: number;
    active: number;
  };
}
