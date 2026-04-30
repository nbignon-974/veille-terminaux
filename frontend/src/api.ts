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

const BASE = import.meta.env.VITE_API_URL ?? "";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
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

  getScrapeStatus: (runId: number) =>
    apiFetch<ScrapeStatus>(`/scrape/${runId}`),

  getScrapeRuns: () => apiFetch<ScrapeRun[]>("/scrape/runs"),
};
