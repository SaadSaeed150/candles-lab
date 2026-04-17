export interface Candle {
  symbol?: string;
  exchange?: string;
  timeframe?: string;
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Trade {
  id?: number;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number;
  quantity: number;
  pnl: number;
  net_pnl?: number;
  commission?: number;
  slippage?: number;
  opened_at: string;
  closed_at: string;
}

export interface Metrics {
  total_trades: number;
  total_pnl: number;
  total_net_pnl: number;
  total_commission: number;
  total_slippage: number;
  win_count: number;
  loss_count: number;
  win_rate: number;
  profit_factor: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  max_drawdown_pct: number;
  max_consecutive_wins: number;
  max_consecutive_losses: number;
  avg_win: number;
  avg_loss: number;
  expectancy: number;
  cagr: number;
}

export interface StrategyRun {
  id: number;
  strategy_name: string;
  mode: string;
  symbol: string;
  exchange: string;
  timeframe: string;
  status: string;
  initial_balance: number;
  final_balance: number | null;
  metrics: Metrics | null;
  config: Record<string, unknown>;
  created_at: string;
  finished_at: string | null;
}

export interface EquityPoint {
  timestamp: string;
  balance: number;
  unrealised_pnl: number;
  total_equity: number;
  drawdown: number;
}

export interface Signal {
  id: number;
  timestamp: string;
  action: string;
  price: number;
  confidence: number;
  stop_loss: number | null;
  take_profit: number | null;
  meta: Record<string, unknown>;
}

export interface BacktestReport {
  overview: {
    strategy: string;
    symbol: string;
    ticks_processed: number;
    duration_seconds: number;
  };
  performance: Metrics;
  pnl: {
    total_pnl: number;
    total_net_pnl: number;
    total_commission: number;
    final_balance: number;
  };
  trades: Trade[];
  equity_curve: EquityPoint[];
  trade_distribution: Record<string, number>;
  monthly_returns: Record<string, number>;
  signals_count: number;
}

export interface User {
  id: number;
  username: string;
  email: string;
}
