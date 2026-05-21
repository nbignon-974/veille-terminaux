import { useMemo, useState } from "react";
import { Phone } from "../api";
import { OPERATOR_BADGE } from "../operatorColors";

interface Props {
  phones: Phone[];
}

interface GroupInfo {
  key: string;
  label: string;
  vendors: { operator: string; price: number; phone: Phone }[];
}

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

function extractStorageFromText(text: string): { storage: string | null; cleaned: string } {
  let storage: string | null = null;
  const explicit = Array.from(text.matchAll(STORAGE_RE));
  if (explicit.length > 0) {
    const m = explicit[0];
    storage = `${m[1]}${m[2].toLowerCase() === "to" ? "to" : "go"}`;
  }
  let cleaned = text.replace(STORAGE_RE, " ");

  // Fallback: bare number from the known-storage list (e.g. "iPhone 16e 256")
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

function normalizeStorage(s: string | null | undefined): string {
  if (!s) return "";
  const { storage } = extractStorageFromText(s);
  return storage ?? s.toLowerCase().replace(/\s+/g, "");
}

function stripColorWords(text: string): string {
  return text
    .split(/[\s,;./\-()]+/)
    .filter((w) => w && !COLOR_WORDS.has(w.toLowerCase()))
    .join(" ")
    .trim();
}

function resolveStorageAndModel(p: Phone): { storage: string; model: string } {
  const fromModel = extractStorageFromText(p.model);
  const storage = normalizeStorage(p.storage) || fromModel.storage || "";
  const model = stripColorWords(fromModel.cleaned);
  return { storage, model };
}

function normalizeKey(p: Phone): string {
  const { storage, model } = resolveStorageAndModel(p);
  return `${p.brand.toLowerCase().trim()}|${model.toLowerCase()}|${storage}`;
}

function shortLabel(p: Phone): string {
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

export function PriceCompare({ phones }: Props) {
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);

  const { operatorKeys, groups, maxPrice } = useMemo(() => {
    // Group phones by brand+model+storage, ignoring color
    const map = new Map<string, GroupInfo>();

    for (const p of phones) {
      const price = p.latest_snapshot?.price_nu;
      if (price == null) continue;

      const key = normalizeKey(p);
      if (!map.has(key)) {
        map.set(key, { key, label: shortLabel(p), vendors: [] });
      }
      const group = map.get(key)!;

      // Keep the cheapest price per vendor within this group
      const existing = group.vendors.find((v) => v.operator === p.operator);
      if (existing) {
        if (price < existing.price) {
          existing.price = price;
          existing.phone = p;
        }
      } else {
        group.vendors.push({ operator: p.operator, price, phone: p });
      }
    }

    const opSet = new Set<string>();
    let maxPrice = 0;
    for (const g of map.values()) {
      for (const v of g.vendors) {
        opSet.add(v.operator);
        if (v.price > maxPrice) maxPrice = v.price;
      }
    }
    const operatorKeys = Array.from(opSet).sort((a, b) => {
      const order = (op: string) =>
        op === "orange_re" ? 0 : op === "sfr_re" ? 1 : 2;
      const oa = order(a);
      const ob = order(b);
      return oa !== ob ? oa - ob : a.localeCompare(b);
    });

    const groups = Array.from(map.values()).sort((a, b) =>
      a.label.localeCompare(b.label)
    );

    return { operatorKeys, groups, maxPrice };
  }, [phones]);

  if (groups.length === 0) {
    return (
      <p className="no-data" style={{ padding: "2rem" }}>
        Aucun prix à comparer. Affinez votre recherche.
      </p>
    );
  }

  return (
    <div className="price-compare">
      <div className="compare-chart-wrap">
        <div className="pc-legend">
          {operatorKeys.map((op) => (
            <span key={op} className="pc-legend-item">
              <span
                className="pc-legend-swatch"
                style={{ background: OPERATOR_BADGE[op]?.color ?? "#888" }}
              />
              {OPERATOR_BADGE[op]?.label ?? op}
            </span>
          ))}
        </div>
        <div className="pc-list">
          {groups.map((g) => (
            <div className="pc-group" key={g.key}>
              <div
                className="pc-label"
                onMouseEnter={() => setHoveredKey(g.key)}
                onMouseLeave={() => setHoveredKey(null)}
              >
                {g.label}
                <span className="pc-count">×{g.vendors.length}</span>
                {hoveredKey === g.key && (
                  <div className="pc-popover">
                    <div className="pc-popover-title">
                      Références regroupées ({g.vendors.length})
                    </div>
                    <ul>
                      {g.vendors.map((v) => (
                        <li key={v.operator}>
                          <span
                            className="vendor-badge"
                            style={{
                              background:
                                OPERATOR_BADGE[v.operator]?.color ?? "#666",
                            }}
                          >
                            {OPERATOR_BADGE[v.operator]?.label ?? v.operator}
                          </span>
                          <span className="pc-popover-name">
                            {v.phone.name}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
              <div className="pc-bars">
                {g.vendors
                  .slice()
                  .sort((a, b) => a.price - b.price)
                  .map((v) => (
                    <div className="pc-bar-row" key={v.operator}>
                      <div
                        className="pc-bar"
                        style={{
                          width: `${(v.price / maxPrice) * 100}%`,
                          background:
                            OPERATOR_BADGE[v.operator]?.color ?? "#888",
                        }}
                        title={`${OPERATOR_BADGE[v.operator]?.label ?? v.operator} : ${v.price.toFixed(2).replace(".", ",")} €`}
                      />
                      <span className="pc-bar-price">
                        {v.price.toFixed(2).replace(".", ",")} €
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Summary table */}
      <table className="compare-table">
        <thead>
          <tr>
            <th>Modèle</th>
            {operatorKeys.map((op) => (
              <th key={op} style={{ color: OPERATOR_BADGE[op]?.color }}>
                {OPERATOR_BADGE[op]?.label ?? op}
              </th>
            ))}
            <th>Meilleur prix</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => {
            const best = g.vendors.reduce(
              (a, b) => (a.price <= b.price ? a : b),
              g.vendors[0]
            );
            return (
              <tr key={g.label}>
                <td className="compare-model">
                  <div className="compare-model-text">{g.label}</div>
                </td>
                {operatorKeys.map((op) => {
                  const v = g.vendors.find((x) => x.operator === op);
                  const isBest = v && v.price === best.price;
                  const planPrices = v?.phone.latest_snapshot?.plan_prices ?? [];
                  let selectedPrice: number | null = null;
                  if (v?.operator === "orange_re") {
                    // Orange: forfait grand public 250 Go GP
                    const gp = planPrices.find(
                      (pp) => pp.plan_name === "250 Go GP" && pp.price_device != null,
                    );
                    selectedPrice = gp?.price_device ?? null;
                  } else {
                    selectedPrice = planPrices
                      .filter((pp) => pp.price_device != null && pp.engagement_months === 24)
                      .reduce((min, pp) => (min == null || pp.price_device! < min ? pp.price_device! : min), null as number | null);
                  }
                  const tiers: [string, number][] = selectedPrice != null ? [["24", selectedPrice]] : [];
                  return (
                    <td
                      key={op}
                      className={isBest ? "compare-best" : ""}
                      style={{ whiteSpace: "normal" }}
                    >
                      {v ? (
                        <div className="compare-prices">
                          {v.phone.latest_snapshot?.price_nu != null && (
                            <div className="compare-price-line">
                              {v.phone.page_url ? (
                                <a href={v.phone.page_url} target="_blank" rel="noopener noreferrer">
                                  {v.price.toFixed(2).replace(".", ",")} €
                                </a>
                              ) : (
                                <span>{v.price.toFixed(2).replace(".", ",")} €</span>
                              )}
                              <span className="engagement-label">nu</span>
                            </div>
                          )}
                          {tiers.map(([months, price]) => (
                            <div key={months} className="compare-price-line">
                              <span>{price.toFixed(2).replace(".", ",")} €</span>
                              <span className="engagement-label">
                                {Number(months) === 0 ? "sans eng." : `${months}m`}
                              </span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <span className="compare-na">—</span>
                      )}
                    </td>
                  );
                })}
                <td className="compare-winner">
                  <div className="compare-winner-inner">
                    <span
                      className="vendor-badge"
                      style={{
                        background: OPERATOR_BADGE[best.operator]?.color ?? "#666",
                      }}
                    >
                      {OPERATOR_BADGE[best.operator]?.label ?? best.operator}
                    </span>
                    {best.price.toFixed(2).replace(".", ",")} €
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
