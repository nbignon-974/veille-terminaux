import { Phone } from "../api";

const COLOR_WORDS = new Set([
  // FR de base + variantes flexionnées (m/f, sg/pl)
  "noir", "noire", "noirs", "noires",
  "blanc", "blanche", "blancs", "blanches",
  "bleu", "bleue", "bleus", "bleues",
  "rouge", "rouges",
  "vert", "verte", "verts", "vertes",
  "jaune", "jaunes",
  "rose", "roses",
  "violet", "violette", "violets", "violettes",
  "gris", "grise", "grises",
  // FR marketing
  "argent", "argenté", "argentée", "argentés", "argentées",
  "or", "doré", "dorée", "dorés", "dorées",
  "lavande", "sable", "marine", "lilas", "neige", "porcelaine", "titane",
  "graphite", "platine", "obsidienne", "cuivre", "bronze", "carmin",
  "corail", "perle", "ivoire", "sapin", "ocean", "océan", "menthe",
  "crème", "creme", "pêche", "peche", "minuit", "stellaire", "aurore",
  "cosmique", "sidéral", "sideral", "profond", "intense", "clair",
  "foncé", "fonce", "mat", "mate", "métallique", "metallique",
  "anthracite", "charbon", "carbone", "mocha", "moka", "ultramarine",
  "ultramarin", "sahara", "canyon",
  // EN de base
  "black", "white", "blue", "red", "green", "yellow", "pink", "purple",
  "gray", "grey", "silver", "gold",
  // EN marketing Apple / Samsung / Pixel / Xiaomi / OnePlus / Honor
  "lavender", "midnight", "starlight", "mist", "cosmos", "sage",
  "citrine", "natural", "desert", "titanium", "alpine", "sierra",
  "phantom", "mystic", "onyx", "obsidian", "porcelain", "hazel", "bay",
  "wintergreen", "charcoal", "snow", "lemongrass", "coral", "glacier",
  "frost", "forest", "aurora", "astro", "pearl", "ivory", "titan",
  "chrome", "sandstone", "volcanic", "glacial", "chromatic", "aqua",
  "meteor", "emerald", "sunrise", "navy", "teal", "peach", "copper",
  "beige", "indigo", "cream", "mint", "sky", "burgundy", "lime",
  "aura", "platinum", "carbon", "crystal",
  // Variantes techniques non-différenciantes commercialement
  "esim",
]);

const STORAGE_RE = /(\d+)\s*(g[ob]|to)\b/gi;
const KNOWN_BARE_STORAGES = [1024, 512, 256, 128, 64];
const BARE_STORAGE_RE = new RegExp(
  `\\b(${KNOWN_BARE_STORAGES.join("|")})\\b`,
);

export function extractStorageFromText(text: string): { storage: string | null; cleaned: string } {
  let storage: string | null = null;
  const explicit = Array.from(text.matchAll(STORAGE_RE));
  if (explicit.length > 0) {
    const m = explicit[0];
    storage = `${m[1]}${m[2].toLowerCase() === "to" ? "to" : "go"}`;
  }
  let cleaned = text.replace(STORAGE_RE, " ");

  if (!storage) {
    const bare = cleaned.match(BARE_STORAGE_RE);
    if (bare) {
      storage = `${bare[1]}go`;
      cleaned = cleaned.replace(BARE_STORAGE_RE, " ");
    }
  }

  cleaned = cleaned.replace(/\s+/g, " ").trim();
  return { storage, cleaned };
}

export function normalizeStorage(s: string | null | undefined): string {
  if (!s) return "";
  const { storage } = extractStorageFromText(s);
  return storage ?? s.toLowerCase().replace(/\s+/g, "");
}

export function stripColorWords(text: string): string {
  return text
    .split(/[\s,;./\-()]+/)
    .filter((w) => w && !COLOR_WORDS.has(w.toLowerCase()))
    .join(" ")
    .trim();
}

export function resolveStorageAndModel(p: Phone): { storage: string; model: string } {
  const fromModel = extractStorageFromText(p.model);
  const storage = normalizeStorage(p.storage) || fromModel.storage || "";
  const model = stripColorWords(fromModel.cleaned);
  return { storage, model };
}

export function normalizeKey(p: Phone): string {
  const { storage, model } = resolveStorageAndModel(p);
  return `${p.brand.toLowerCase().trim()}|${model.toLowerCase()}|${storage}`;
}

export function shortLabel(p: Phone): string {
  const { storage, model } = resolveStorageAndModel(p);
  const goMatch = storage.match(/^(\d+)go$/);
  const toMatch = storage.match(/^(\d+)to$/);
  const storageLabel = goMatch
    ? `${goMatch[1]} Go`
    : toMatch
    ? `${toMatch[1]} To`
    : storage;
  return [model, storageLabel].filter(Boolean).join(" ");
}

/** Orange forfait "grand public" price extraction. */
export function getOrange24mPrice(phone: Phone): number | null {
  const planPrices = phone.latest_snapshot?.plan_prices ?? [];
  const gp = planPrices.find(
    (pp) => pp.plan_name === "250 Go GP" && pp.price_device != null,
  );
  return gp?.price_device ?? null;
}

/** Cheapest 24-month engagement price for non-Orange operators. */
export function getCompetitor24mPrice(phone: Phone): number | null {
  const planPrices = phone.latest_snapshot?.plan_prices ?? [];
  return planPrices
    .filter((pp) => pp.price_device != null && pp.engagement_months === 24)
    .reduce(
      (min, pp) => (min == null || pp.price_device! < min ? pp.price_device! : min),
      null as number | null,
    );
}

/** Returns the "24m" price for the given phone, picking the right plan per operator. */
export function get24mPrice(phone: Phone): number | null {
  return phone.operator === "orange_re"
    ? getOrange24mPrice(phone)
    : getCompetitor24mPrice(phone);
}

export interface VendorEntry {
  operator: string;
  phone: Phone;
  priceNu: number | null;
  price24m: number | null;
}

export interface PhoneGroup {
  key: string;
  label: string;
  brand: string;
  vendors: VendorEntry[];
}

/**
 * Group phones by brand+model+storage (ignoring color).
 * For each operator inside a group, we keep the cheapest variant (by nu price when available,
 * otherwise by 24m price), and expose both nu and 24m prices for that variant.
 */
export function groupPhones(phones: Phone[]): PhoneGroup[] {
  const map = new Map<string, PhoneGroup>();

  for (const p of phones) {
    const priceNu = p.latest_snapshot?.price_nu ?? null;
    const price24m = get24mPrice(p);
    if (priceNu == null && price24m == null) continue;

    const key = normalizeKey(p);
    if (!map.has(key)) {
      map.set(key, { key, label: shortLabel(p), brand: p.brand, vendors: [] });
    }
    const group = map.get(key)!;

    const existing = group.vendors.find((v) => v.operator === p.operator);
    const compare = (a: VendorEntry, b: VendorEntry): number => {
      const ap = a.priceNu ?? a.price24m ?? Infinity;
      const bp = b.priceNu ?? b.price24m ?? Infinity;
      return ap - bp;
    };
    const candidate: VendorEntry = { operator: p.operator, phone: p, priceNu, price24m };
    if (!existing) {
      group.vendors.push(candidate);
    } else if (compare(candidate, existing) < 0) {
      Object.assign(existing, candidate);
    }
  }

  return Array.from(map.values()).sort((a, b) => a.label.localeCompare(b.label));
}
