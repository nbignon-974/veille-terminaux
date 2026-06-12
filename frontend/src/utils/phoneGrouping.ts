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
  "lavande", "sable", "marine", "nuit", "lilas", "neige", "porcelaine", "titane",
  "graphite", "platine", "obsidienne", "cuivre", "bronze", "carmin",
  "corail", "perle", "ivoire", "sapin", "ocean", "océan", "menthe",
  "crème", "creme", "pêche", "peche", "minuit", "stellaire", "aurore",
  "cosmique", "sidéral", "sideral", "profond", "intense", "clair",
  "foncé", "fonce", "mat", "mate", "métallique", "metallique",
  "anthracite", "charbon", "carbone", "mocha", "moka", "ultramarine",
  "ultramarin", "outremer", "sarcelle", "stellar", "space", "sahara", "canyon",
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
  "aura", "platinum", "carbon", "crystal", "naturel", "deep",
  // Variantes techniques non-différenciantes commercialement
  "esim",
]);

// Strip diacritics so ASCII regex word-boundaries work (JS \b doesn't treat "é"
// as a word char, so e.g. "\brefé\b" never matches) and so accented colours
// still match after the model text is de-accented.
const deaccent = (s: string): string =>
  s.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
const COLOR_WORDS_NA = new Set(Array.from(COLOR_WORDS, deaccent));

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

// Descriptive noise that varies between vendors for the SAME phone: screen size,
// OS, connector, SIM type, warranty/condition blurbs, RAM specs, trailing "…".
// Removed before keying so e.g. leclic's
//   'iphone 16 pro max 17,5 cm (6.9") double sim ios 18 usb type-c'
// keys the same as Orange's "iPhone 16 Pro Max 256 Go".
// Significant tokens (pro / max / plus / ultra / mini / fe / 4g / 5g …) are kept,
// so distinct products are never merged.
const NOISE_RE = new RegExp(
  [
    "\\(.*?\\)", // parentheticals e.g. (6.9")
    "\\d+[.,]\\d+\\s*cm", // screen size 17,5 cm
    "\\d+[.,]\\d+\\s*\"", // inches 6.9"
    "\\bios\\s*\\d+\\b",
    "\\bandroid\\s*\\d+\\b",
    "\\busb\\s*type-?c\\b",
    "\\btype-?c\\b",
    "\\bdouble\\s*sim\\b",
    "\\bdual\\s*sim\\b",
    "\\bnano\\s*sim\\b",
    "\\be?sim\\b",
    "\\bsmartphones?\\b",
    "\\bt[ée]l[ée]phones?\\b",
    "\\bgarantie\\b.*", // warranty blurb to end of string
    "\\bgrade\\s*[a-c]\\+?\\b", // "grade A+", "grade B"
    "\\b[a-c]\\+", // standalone refurbished grade "A+/B+/C+" (never matches S26+/Pro+)
    "\\b[a-d]\\b", // lone grade letter ("… 128 Go A") — no phone model is a bare a/b/c/d
    "\\brec(onditionn[ée])?\\b",
    "\\brenewed\\b",
    "\\brefurb\\w*\\b",
    "\\bref[ée]\\b",
    "\\boccasion\\b",
    "\\d+\\s*/\\s*\\d*\\s*(go|gb)?", // RAM spec 6/128, 8/256 go, truncated 6/
    "\\bram\\b",
    "\\d+\\s*mah\\b", // battery capacity 5000 mAh
    "\\bgsm\\b",
    "\\.\\.\\.", // trailing ellipsis
  ].join("|"),
  "gi",
);

const BRAND_ALIASES: Record<string, string> = {
  // Some vendors put "iPhone" in the brand column instead of "Apple".
  iphone: "apple",
};

export function normalizeBrand(brand: string): string {
  const b = brand.toLowerCase().trim();
  return BRAND_ALIASES[b] ?? b;
}

const KNOWN_BRANDS = new Set([
  "apple", "samsung", "xiaomi", "honor", "huawei", "google", "oppo",
  "motorola", "crosscall", "nokia", "realme", "oneplus", "nothing", "cmf",
  "fairphone", "vivo", "sony", "asus", "poco", "tcl", "wiko", "doro", "zte",
  "blackview", "ulefone", "beafon", "oscal", "redmi", "nubia",
]);

// When the parsed brand is junk (e.g. Ravate puts "ReFé" — a reseller tag — in
// the brand column for some refurbished items), infer it from the model name.
const MODEL_BRAND_HINTS: [RegExp, string][] = [
  [/\biphone\b/i, "apple"],
  [/\bgalaxy\b/i, "samsung"],
  [/\b(redmi|poco)\b/i, "xiaomi"],
  [/\bpixel\b/i, "google"],
  [/\b(moto|razr)\b/i, "motorola"],
];

export function resolveBrand(p: Phone): string {
  const b = normalizeBrand(p.brand);
  if (KNOWN_BRANDS.has(b)) return b;
  for (const [re, brand] of MODEL_BRAND_HINTS) {
    if (re.test(p.model)) return brand;
  }
  return b;
}

/**
 * Canonical model string used for grouping. Strips vendor-specific descriptive
 * noise and colours, and turns "+" (Plus variant) into a "plus" token so e.g.
 * "Galaxy S26+" never collapses onto "Galaxy S26". Case is preserved so the
 * result doubles as a display label; the key lower-cases it.
 */
export function cleanModel(text: string): string {
  // De-accent first so ASCII regexes (and the JS \b boundary) behave; "ReFé" and
  // "reconditionné" only get stripped once they are "refe"/"reconditionne".
  let t = deaccent(text);
  t = t.replace(/\bpro\s*max\b/gi, "pro max"); // unify "ProMax" / "Pro  Max"
  // Strip noise (incl. refurbished grade markers like "A+") BEFORE turning a
  // model "+" into "plus", otherwise "A+" would survive as a stray "a plus".
  t = t.replace(NOISE_RE, " ");
  t = t.replace(/\+/g, " plus ");
  t = t
    .split(/[\s,;./\-()]+/)
    .filter((w) => w && !COLOR_WORDS_NA.has(w.toLowerCase()))
    .join(" ");
  return t.replace(/\s+/g, " ").trim();
}

export function resolveStorageAndModel(p: Phone): { storage: string; model: string } {
  const fromModel = extractStorageFromText(p.model);
  const storage = normalizeStorage(p.storage) || fromModel.storage || "";
  const model = cleanModel(fromModel.cleaned);
  return { storage, model };
}

export function normalizeKey(p: Phone): string {
  const { storage, model } = resolveStorageAndModel(p);
  // New and refurbished are never compared together (different products/prices).
  const condition = p.is_refurbished ? "refurb" : "new";
  return `${resolveBrand(p)}|${model.toLowerCase()}|${storage}|${condition}`;
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
  const base = [model, storageLabel].filter(Boolean).join(" ");
  return p.is_refurbished ? `${base} (recond.)` : base;
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
