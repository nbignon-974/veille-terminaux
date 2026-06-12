export interface PlanPrice {
  plan_name: string;
  price_monthly: number | null;
  price_device: number | null;
  engagement_months: number | null;
}

export interface Snapshot {
  id: number;
  scraped_at: string;
  price_nu: number | null;
  promotion: string | null;
  plan_prices: PlanPrice[];
}

export interface Phone {
  id: number;
  sfr_id: string | null;
  name: string;
  brand: string;
  model: string;
  storage: string | null;
  color: string | null;
  image_url: string | null;
  page_url: string | null;
  operator: string;
  product_type: string;
  is_refurbished: boolean;
  latest_snapshot: Snapshot | null;
}

export interface ScrapeRun {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: "pending" | "running" | "done" | "error";
  phones_found: number;
  phones_scraped: number;
  error_message: string | null;
  operator: string;
}

export interface ScrapeStatus {
  run_id: number;
  status: "pending" | "running" | "done" | "error";
  phones_found: number;
  phones_scraped: number;
  finished_at: string | null;
  error_message: string | null;
  operator: string;
}

export interface Operator {
  id: string;
  label: string;
}

export interface ScrapeHealth {
  operator: string;
  label: string;
  state: "ko" | "warning";
  reason: string;
  last_run_id: number | null;
  last_status: string | null;
  last_count: number | null;
  prev_count: number | null;
  last_at: string | null;
}

const BASE = import.meta.env.VITE_API_URL ?? "";
const API_KEY = import.meta.env.VITE_API_KEY ?? "";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (API_KEY) headers.set("X-API-Key", API_KEY);
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  getPhones: (brand?: string, search?: string, operator?: string, productType?: string, isRefurbished?: boolean) => {
    const params = new URLSearchParams();
    if (brand) params.set("brand", brand);
    if (search) params.set("search", search);
    if (operator) params.set("operator", operator);
    if (productType) params.set("product_type", productType);
    if (isRefurbished !== undefined) params.set("is_refurbished", String(isRefurbished));
    const qs = params.toString();
    return apiFetch<Phone[]>(`/phones${qs ? `?${qs}` : ""}`);
  },

  getPhoneHistory: (phoneId: number) =>
    apiFetch<Snapshot[]>(`/phones/${phoneId}/history`),

  getBrands: (operator?: string) => {
    const params = new URLSearchParams();
    if (operator) params.set("operator", operator);
    const qs = params.toString();
    return apiFetch<string[]>(`/brands${qs ? `?${qs}` : ""}`);
  },

  getOperators: () => apiFetch<Operator[]>("/operators"),

  startScrape: (operator: string = "sfr_re") =>
    apiFetch<ScrapeRun>(`/scrape?operator=${encodeURIComponent(operator)}`, { method: "POST" }),

  startScrapeAll: () => apiFetch<ScrapeRun[]>(`/scrape/all`, { method: "POST" }),

  getScrapeStatus: (runId: number) =>
    apiFetch<ScrapeStatus>(`/scrape/${runId}`),

  getScrapeRuns: () => apiFetch<ScrapeRun[]>("/scrape/runs"),

  getScrapeHealth: () => apiFetch<ScrapeHealth[]>("/scrape/health"),

  importOrangeCsv: async (file: File): Promise<ScrapeRun> => {
    const form = new FormData();
    form.append("file", file);
    const headers = new Headers();
    if (API_KEY) headers.set("X-API-Key", API_KEY);
    const res = await fetch(`${BASE}/import/orange`, { method: "POST", body: form, headers });
    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText);
      throw new Error(`${res.status} ${text}`);
    }
    return res.json() as Promise<ScrapeRun>;
  },
};
