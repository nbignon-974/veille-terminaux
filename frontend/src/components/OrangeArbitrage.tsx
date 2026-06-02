import { useMemo, useState } from "react";
import { Phone } from "../api";
import { OPERATOR_BADGE } from "../operatorColors";
import { groupPhones, PhoneGroup, VendorEntry } from "../utils/phoneGrouping";

type Mode = "lose" | "win";
type Axis = "nu" | "m24";

interface Props {
  phones: Phone[];
  mode: Mode;
}

interface ArbitrageRow {
  group: PhoneGroup;
  orange: VendorEntry;
  competitors: VendorEntry[];
  bestCompetitorPrice: number; // strictly the best (lowest) competitor price on the chosen axis
  bestCompetitorVendors: VendorEntry[]; // ties on best price
  orangePrice: number;
  gap: number; // orangePrice - bestCompetitorPrice (negative = Orange cheaper)
  gapPct: number; // gap / orangePrice
}

function getPrice(v: VendorEntry, axis: Axis): number | null {
  return axis === "nu" ? v.priceNu : v.price24m;
}

function formatPrice(n: number): string {
  return `${n.toFixed(2).replace(".", ",")} €`;
}

function formatSignedPrice(n: number): string {
  const sign = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${sign}${Math.abs(n).toFixed(2).replace(".", ",")} €`;
}

function formatSignedPct(n: number): string {
  const sign = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${sign}${(Math.abs(n) * 100).toFixed(1).replace(".", ",")} %`;
}

const AXIS_LABEL: Record<Axis, string> = {
  nu: "Achat nu",
  m24: "Forfait + mobile (24m)",
};

export function OrangeArbitrage({ phones, mode }: Props) {
  const [axis, setAxis] = useState<Axis>("nu");
  const [refurbFilter, setRefurbFilter] = useState<"new" | "refurb">("new");
  const [brandFilter, setBrandFilter] = useState<string>("");

  const filteredPhones = useMemo(
    () =>
      phones.filter((p) => {
        if (p.product_type !== "phone") return false;
        if (refurbFilter === "new" && p.is_refurbished) return false;
        if (refurbFilter === "refurb" && !p.is_refurbished) return false;
        return true;
      }),
    [phones, refurbFilter],
  );

  const { rows, brands } = useMemo(() => {
    const groups = groupPhones(filteredPhones);
    const rows: ArbitrageRow[] = [];

    for (const g of groups) {
      const orange = g.vendors.find((v) => v.operator === "orange_re");
      if (!orange) continue;
      const orangePrice = getPrice(orange, axis);
      if (orangePrice == null) continue;

      const competitors = g.vendors.filter(
        (v) => v.operator !== "orange_re" && getPrice(v, axis) != null,
      );
      if (competitors.length === 0) continue;

      const competitorPrices = competitors.map((v) => getPrice(v, axis)!);
      const bestCompetitorPrice = Math.min(...competitorPrices);
      const bestCompetitorVendors = competitors.filter(
        (v) => getPrice(v, axis)! === bestCompetitorPrice,
      );

      const gap = orangePrice - bestCompetitorPrice;
      const matches =
        mode === "lose"
          ? gap > 0
          : gap < 0 || (gap === 0 && competitors.length >= 1);
      if (!matches) continue;

      rows.push({
        group: g,
        orange,
        competitors,
        bestCompetitorPrice,
        bestCompetitorVendors,
        orangePrice,
        gap,
        gapPct: orangePrice !== 0 ? gap / orangePrice : 0,
      });
    }

    // Tri : écart absolu décroissant. Pour "lose" on veut le plus gros écart > 0 en haut ;
    // pour "win" l'écart est négatif, on trie par |gap| décroissant.
    rows.sort((a, b) => Math.abs(b.gap) - Math.abs(a.gap));

    const brandSet = new Set<string>();
    for (const r of rows) brandSet.add(r.group.brand);
    const brands = Array.from(brandSet).sort((a, b) => a.localeCompare(b));

    return { rows, brands };
  }, [filteredPhones, axis, mode]);

  const visibleRows = useMemo(
    () => (brandFilter ? rows.filter((r) => r.group.brand === brandFilter) : rows),
    [rows, brandFilter],
  );

  const averageGap = useMemo(
    () =>
      visibleRows.length === 0
        ? 0
        : visibleRows.reduce((sum, r) => sum + Math.abs(r.gap), 0) / visibleRows.length,
    [visibleRows],
  );

  const headline = mode === "lose"
    ? "Orange doit faire mieux"
    : "Orange champion";

  const subline = mode === "lose"
    ? "Modèles où Orange est plus cher qu'au moins un revendeur concurrent."
    : "Modèles où Orange est strictement moins cher que tous les revendeurs concurrents.";

  return (
    <div className="arbitrage">
      <div className="arbitrage-header">
        <div>
          <h2 className="arbitrage-title">{headline}</h2>
          <p className="arbitrage-sub">{subline}</p>
        </div>
        <div className="arbitrage-stats">
          <div className="arbitrage-stat">
            <div className="arbitrage-stat-value">{visibleRows.length}</div>
            <div className="arbitrage-stat-label">
              {visibleRows.length > 1 ? "modèles concernés" : "modèle concerné"}
            </div>
          </div>
          <div className="arbitrage-stat">
            <div className={`arbitrage-stat-value ${mode === "lose" ? "loss" : "win"}`}>
              {averageGap > 0 ? formatPrice(averageGap) : "—"}
            </div>
            <div className="arbitrage-stat-label">
              {mode === "lose" ? "écart moyen à rattraper" : "économie moyenne vs concurrents"}
            </div>
          </div>
        </div>
      </div>

      <div className="arbitrage-filters">
        <div className="arbitrage-filter-group">
          <span className="arbitrage-filter-label">Type de prix</span>
          <div className="arbitrage-toggle">
            <button
              className={axis === "nu" ? "active" : ""}
              onClick={() => setAxis("nu")}
            >
              {AXIS_LABEL.nu}
            </button>
            <button
              className={axis === "m24" ? "active" : ""}
              onClick={() => setAxis("m24")}
            >
              {AXIS_LABEL.m24}
            </button>
          </div>
        </div>

        <div className="arbitrage-filter-group">
          <span className="arbitrage-filter-label">État</span>
          <div className="arbitrage-toggle">
            <button
              className={refurbFilter === "new" ? "active" : ""}
              onClick={() => setRefurbFilter("new")}
            >
              Neuf
            </button>
            <button
              className={refurbFilter === "refurb" ? "active" : ""}
              onClick={() => setRefurbFilter("refurb")}
            >
              Reconditionné
            </button>
          </div>
        </div>

        <div className="arbitrage-filter-group">
          <span className="arbitrage-filter-label">Marque</span>
          <select
            value={brandFilter}
            onChange={(e) => setBrandFilter(e.target.value)}
            className="brand-select"
          >
            <option value="">Toutes les marques</option>
            {brands.map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </select>
        </div>
      </div>

      {visibleRows.length === 0 ? (
        <p className="no-data" style={{ padding: "2rem" }}>
          Aucun modèle ne correspond à ces critères.
        </p>
      ) : (
        <div className="arbitrage-table-wrap">
          <table className="arbitrage-table">
            <thead>
              <tr>
                <th>Modèle</th>
                <th>Orange</th>
                <th>{mode === "lose" ? "Concurrents moins chers" : "Concurrents plus chers"}</th>
                <th>Écart</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((r) => {
                const cheaperCompetitors = r.competitors
                  .filter((v) => {
                    const p = getPrice(v, axis)!;
                    return mode === "lose" ? p < r.orangePrice : p > r.orangePrice;
                  })
                  .sort((a, b) => getPrice(a, axis)! - getPrice(b, axis)!);

                return (
                  <tr key={r.group.key + axis}>
                    <td className="arbitrage-model">
                      <div className="arbitrage-model-text">{r.group.label}</div>
                      <div className="arbitrage-brand">{r.group.brand}</div>
                    </td>
                    <td className="arbitrage-orange">
                      {r.orange.phone.page_url ? (
                        <a
                          href={r.orange.phone.page_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="arbitrage-price-link"
                        >
                          {formatPrice(r.orangePrice)}
                        </a>
                      ) : (
                        <span>{formatPrice(r.orangePrice)}</span>
                      )}
                    </td>
                    <td className="arbitrage-competitors">
                      {cheaperCompetitors.length === 0 ? (
                        <span className="compare-na">—</span>
                      ) : (
                        <ul className="arbitrage-competitor-list">
                          {cheaperCompetitors.map((v) => {
                            const p = getPrice(v, axis)!;
                            const delta = p - r.orangePrice;
                            const isBest = p === r.bestCompetitorPrice;
                            return (
                              <li key={v.operator} className={isBest ? "best" : ""}>
                                <span
                                  className="vendor-badge"
                                  style={{
                                    background:
                                      OPERATOR_BADGE[v.operator]?.color ?? "#666",
                                  }}
                                >
                                  {OPERATOR_BADGE[v.operator]?.label ?? v.operator}
                                </span>
                                {v.phone.page_url ? (
                                  <a
                                    href={v.phone.page_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                  >
                                    {formatPrice(p)}
                                  </a>
                                ) : (
                                  <span>{formatPrice(p)}</span>
                                )}
                                <span
                                  className={`arbitrage-delta ${delta < 0 ? "win" : "loss"}`}
                                >
                                  {formatSignedPrice(delta)}
                                </span>
                              </li>
                            );
                          })}
                        </ul>
                      )}
                    </td>
                    <td>
                      <div
                        className={`arbitrage-gap ${mode === "lose" ? "loss" : "win"}`}
                      >
                        <div className="arbitrage-gap-amount">
                          {formatSignedPrice(mode === "win" ? -Math.abs(r.gap) : r.gap)}
                        </div>
                        <div className="arbitrage-gap-pct">
                          {formatSignedPct(mode === "win" ? -Math.abs(r.gapPct) : r.gapPct)}
                        </div>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
