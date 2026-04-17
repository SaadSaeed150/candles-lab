const API_BASE = "/api";

function authHeaders(): HeadersInit {
  const token =
    typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers as Record<string, string>) },
  });

  if (res.status === 401) {
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      return request<T>(path, options);
    }
    if (typeof window !== "undefined") {
      localStorage.removeItem("access_token");
      localStorage.removeItem("refresh_token");
      window.location.href = "/login";
    }
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.error || body.detail || res.statusText, body);
  }

  return res.json();
}

async function tryRefreshToken(): Promise<boolean> {
  const refresh = localStorage.getItem("refresh_token");
  if (!refresh) return false;

  try {
    const res = await fetch(`${API_BASE}/auth/refresh/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    localStorage.setItem("access_token", data.access);
    if (data.refresh) localStorage.setItem("refresh_token", data.refresh);
    return true;
  } catch {
    return false;
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export const api = {
  // Auth
  login: (username: string, password: string) =>
    request<{ access: string; refresh: string }>("/auth/login/", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  register: (username: string, email: string, password: string) =>
    request<{ id: number; username: string; email: string }>("/auth/register/", {
      method: "POST",
      body: JSON.stringify({ username, email, password }),
    }),

  me: () => request<{ id: number; username: string; email: string }>("/auth/me/"),

  // Strategies
  strategies: () => request<{ strategies: string[] }>("/strategies/"),

  // Simulation
  simulate: (params: Record<string, unknown>) =>
    request<Record<string, unknown>>("/simulate/", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  // Backtest
  backtestSync: (params: Record<string, unknown>) =>
    request<Record<string, unknown>>("/backtest/sync/", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  backtestAsync: (params: Record<string, unknown>) =>
    request<{ task_id: string; status: string }>("/backtest/", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  taskStatus: (taskId: string) =>
    request<{ task_id: string; status: string; result?: unknown }>(`/data/task/${taskId}/`),

  // Strategy runs
  runs: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request<StrategyRunResponse[]>(`/runs/${qs}`);
  },

  runDetail: (id: number) => request<StrategyRunResponse>(`/runs/${id}/`),

  runSignals: (id: number) => request<SignalResponse[]>(`/runs/${id}/signals/`),

  runEquity: (id: number) => request<EquityResponse[]>(`/runs/${id}/equity/`),

  // Market data
  marketData: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request<MarketDataResponse[]>(`/market-data/${qs}`);
  },

  // Balance / trades
  balance: () => request<Record<string, unknown>>("/balance/"),
  trades: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request<TradeResponse[]>(`/trades/${qs}`);
  },
};

// Response type aliases (matching DRF serializers)
interface StrategyRunResponse {
  id: number;
  strategy_name: string;
  mode: string;
  symbol: string;
  exchange: string;
  timeframe: string;
  status: string;
  initial_balance: string;
  final_balance: string | null;
  metrics: Record<string, number> | null;
  created_at: string;
  finished_at: string | null;
}

interface SignalResponse {
  id: number;
  timestamp: string;
  action: string;
  price: string;
  confidence: string;
  stop_loss: string | null;
  take_profit: string | null;
  meta: Record<string, unknown>;
}

interface EquityResponse {
  id: number;
  timestamp: string;
  balance: string;
  unrealised_pnl: string;
  total_equity: string;
  drawdown: string;
}

interface MarketDataResponse {
  id: number;
  symbol: string;
  exchange: string;
  timeframe: string;
  time: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
}

interface TradeResponse {
  id: number;
  symbol: string;
  side: string;
  entry_price: string;
  exit_price: string;
  quantity: string;
  pnl: string;
  opened_at: string;
  closed_at: string;
}
