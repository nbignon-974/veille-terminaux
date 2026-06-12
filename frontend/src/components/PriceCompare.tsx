import { useMemo, useState } from "react";
import { Phone } from "../api";
import { OPERATOR_BADGE } from "../operatorColors";
import { groupPhones, get24mPrice } from "../utils/phoneGrouping";

interface Props {
  phones: Phone[];
}

const isRefurbGroup = (g: { vendors: { phone: { is_refurbished: boolean } }[] }) =>
  g.vendors.some((v) => v.phone.is_refurbished);

// In the comparator the new/refurb split is already conveyed by the toggle, so
// drop the redundant "(recond.)" suffix from the displayed model name.
const displayLabel = (label: string) => label.replace(/\s*\(recond\.\)$/, "");

// Highest "nu" price of a group — used to order references by price (so e.g.
// "Pro Max 1 To" ranks above "Pro 1 To" even if the latter has a cheaper offer).
const groupTopPrice = (g: { vendors: { priceNu: number | null }[] }) => {
  const prices = g.vendors
    .map((v) => v.priceNu)
    .filter((p): p is number => p != null);
  return prices.length ? Math.max(...prices) : 0;
};

export function PriceCompare({ phones }: Props) {
  const [hoveredKey, setHoveredKey] = useState<string | null>(null);
  // Comparator-only condition switch — new is shown by default.
  const [condition, setCondition] = useState<"new" | "refurb">("new");

  const allGroups = useMemo(
    () => groupPhones(phones).filter((g) => g.vendors.some((v) => v.priceNu != null)),
    [phones],
  );
  const refurbCount = useMemo(() => allGroups.filter(isRefurbGroup).length, [allGroups]);
  const newCount = allGroups.length - refurbCount;

  const { operatorKeys, groups, maxPrice } = useMemo(() => {
    const groups = allGroups
      .filter((g) => (isRefurbGroup(g) ? "refurb" : "new") === condition)
      .sort((a, b) => groupTopPrice(b) - groupTopPrice(a)); // by highest price, desc

    const opSet = new Set<string>();
    let maxPrice = 0;
    for (const g of groups) {
      for (const v of g.vendors) {
        opSet.add(v.operator);
        if (v.priceNu != null && v.priceNu > maxPrice) maxPrice = v.priceNu;
      }
    }
    const operatorKeys = Array.from(opSet).sort((a, b) => {
      const order = (op: string) =>
        op === "orange_re" ? 0 : op === "sfr_re" ? 1 : 2;
      const oa = order(a);
      const ob = order(b);
      return oa !== ob ? oa - ob : a.localeCompare(b);
    });

    return { operatorKeys, groups, maxPrice };
  }, [allGroups, condition]);

  if (allGroups.length === 0) {
    return (
      <p className="no-data" style={{ padding: "2rem" }}>
        Aucun prix à comparer. Affinez votre recherche.
      </p>
    );
  }

  const conditionToggle = (
    <div className="pc-condition-toggle">
      <button
        className={condition === "new" ? "active" : ""}
        onClick={() => setCondition("new")}
      >
        Neuf <span className="pc-cond-count">{newCount}</span>
      </button>
      <button
        className={condition === "refurb" ? "active" : ""}
        onClick={() => setCondition("refurb")}
        disabled={refurbCount === 0}
      >
        Reconditionné <span className="pc-cond-count">{refurbCount}</span>
      </button>
    </div>
  );

  if (groups.length === 0) {
    return (
      <div className="price-compare">
        <div className="compare-chart-wrap">
          {conditionToggle}
          <p className="no-data" style={{ padding: "1.5rem 0" }}>
            Aucun terminal {condition === "refurb" ? "reconditionné" : "neuf"} à comparer ici.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="price-compare">
      <div className="compare-chart-wrap">
        {conditionToggle}
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
          {groups.map((g) => {
            const nuVendors = g.vendors.filter((v) => v.priceNu != null);
            return (
              <div className="pc-group" key={g.key}>
                <div
                  className="pc-label"
                  onMouseEnter={() => setHoveredKey(g.key)}
                  onMouseLeave={() => setHoveredKey(null)}
                >
                  {displayLabel(g.label)}
                  <span className="pc-count">×{nuVendors.length}</span>
                  {hoveredKey === g.key && (
                    <div className="pc-popover">
                      <div className="pc-popover-title">
                        Références regroupées ({nuVendors.length})
                      </div>
                      <ul>
                        {nuVendors.map((v) => (
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
                  {nuVendors
                    .slice()
                    .sort((a, b) => (b.priceNu ?? 0) - (a.priceNu ?? 0))
                    .map((v) => (
                      <div className="pc-bar-row" key={v.operator}>
                        <div
                          className="pc-bar"
                          style={{
                            width: `${((v.priceNu ?? 0) / maxPrice) * 100}%`,
                            background:
                              OPERATOR_BADGE[v.operator]?.color ?? "#888",
                          }}
                          title={`${OPERATOR_BADGE[v.operator]?.label ?? v.operator} : ${(v.priceNu ?? 0).toFixed(2).replace(".", ",")} €`}
                        />
                        <span className="pc-bar-price">
                          {(v.priceNu ?? 0).toFixed(2).replace(".", ",")} €
                        </span>
                      </div>
                    ))}
                </div>
              </div>
            );
          })}
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
            const nuVendors = g.vendors.filter((v) => v.priceNu != null);
            if (nuVendors.length === 0) return null;
            const best = nuVendors.reduce(
              (a, b) => ((a.priceNu ?? Infinity) <= (b.priceNu ?? Infinity) ? a : b),
              nuVendors[0],
            );
            return (
              <tr key={g.label}>
                <td className="compare-model">
                  <div className="compare-model-text">{displayLabel(g.label)}</div>
                </td>
                {operatorKeys.map((op) => {
                  const v = g.vendors.find((x) => x.operator === op);
                  const isBest = v && v.priceNu != null && v.priceNu === best.priceNu;
                  const selectedPrice = v ? get24mPrice(v.phone) : null;
                  const tiers: [string, number][] = selectedPrice != null ? [["24", selectedPrice]] : [];
                  return (
                    <td
                      key={op}
                      className={isBest ? "compare-best" : ""}
                      style={{ whiteSpace: "normal" }}
                    >
                      {v ? (
                        <div className="compare-prices">
                          {v.priceNu != null && (
                            <div className="compare-price-line">
                              {v.phone.page_url ? (
                                <a href={v.phone.page_url} target="_blank" rel="noopener noreferrer">
                                  {v.priceNu.toFixed(2).replace(".", ",")} €
                                </a>
                              ) : (
                                <span>{v.priceNu.toFixed(2).replace(".", ",")} €</span>
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
                    {best.priceNu!.toFixed(2).replace(".", ",")} €
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
