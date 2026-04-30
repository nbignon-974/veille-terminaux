import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Phone } from "../api";
import { OPERATOR_BADGE } from "../operatorColors";

interface Props {
  phones: Phone[];
}

interface VariantRow {
  label: string;
  [operatorKey: string]: number | string | null;
}

interface GroupInfo {
  label: string;
  vendors: { operator: string; price: number; phone: Phone }[];
}

function normalizeKey(p: Phone): string {
  return `${p.brand}|${p.model}|${p.storage ?? ""}`.toLowerCase().trim();
}

function shortLabel(p: Phone): string {
  const parts = [p.model, p.storage].filter(Boolean);
  return parts.join(" ");
}

export function PriceCompare({ phones }: Props) {
  const { chartData, operatorKeys, groups } = useMemo(() => {
    // Group phones by brand+model+storage, ignoring color
    const map = new Map<string, GroupInfo>();

    for (const p of phones) {
      const price = p.latest_snapshot?.price_nu;
      if (price == null) continue;

      const key = normalizeKey(p);
      if (!map.has(key)) {
        map.set(key, { label: shortLabel(p), vendors: [] });
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

    // Collect all operators present in the data
    const opSet = new Set<string>();
    for (const g of map.values()) {
      for (const v of g.vendors) opSet.add(v.operator);
    }
    const operatorKeys = Array.from(opSet);

    // Build chart data sorted by label
    const groups = Array.from(map.values()).sort((a, b) =>
      a.label.localeCompare(b.label)
    );

    const chartData: VariantRow[] = groups.map((g) => {
      const row: VariantRow = { label: g.label };
      for (const v of g.vendors) {
        row[v.operator] = v.price;
      }
      return row;
    });

    return { chartData, operatorKeys, groups };
  }, [phones]);

  if (chartData.length === 0) {
    return (
      <p className="no-data" style={{ padding: "2rem" }}>
        Aucun prix à comparer. Affinez votre recherche.
      </p>
    );
  }

  const barHeight = Math.max(380, chartData.length * 50);

  return (
    <div className="price-compare">
      <div className="compare-chart-wrap">
        <ResponsiveContainer width="100%" height={barHeight}>
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 8, right: 24, left: 8, bottom: 8 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
            <XAxis
              type="number"
              tickFormatter={(v) => `${v} €`}
              tick={{ fontSize: 12 }}
            />
            <YAxis
              type="category"
              dataKey="label"
              width={200}
              tick={{ fontSize: 12 }}
            />
            <Tooltip
              formatter={(value: number, name: string) => [
                `${value.toFixed(2).replace(".", ",")} €`,
                OPERATOR_BADGE[name]?.label ?? name,
              ]}
              labelStyle={{ fontWeight: 700 }}
              contentStyle={{ borderRadius: 8, fontSize: 13 }}
            />
            <Legend
              formatter={(value: string) =>
                OPERATOR_BADGE[value]?.label ?? value
              }
              wrapperStyle={{ fontSize: "0.82rem", paddingTop: 8 }}
            />
            {operatorKeys.map((op) => (
              <Bar
                key={op}
                dataKey={op}
                name={op}
                fill={OPERATOR_BADGE[op]?.color ?? "#888"}
                radius={[0, 4, 4, 0]}
                barSize={16}
              >
                {chartData.map((entry, i) => (
                  <Cell
                    key={i}
                    fill={OPERATOR_BADGE[op]?.color ?? "#888"}
                    opacity={entry[op] != null ? 1 : 0}
                  />
                ))}
              </Bar>
            ))}
          </BarChart>
        </ResponsiveContainer>
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
                <td className="compare-model">{g.label}</td>
                {operatorKeys.map((op) => {
                  const v = g.vendors.find((x) => x.operator === op);
                  const isBest = v && v.price === best.price;
                  return (
                    <td
                      key={op}
                      className={isBest ? "compare-best" : ""}
                    >
                      {v ? (
                        v.phone.page_url ? (
                          <a
                            href={v.phone.page_url}
                            target="_blank"
                            rel="noopener noreferrer"
                          >
                            {v.price.toFixed(2).replace(".", ",")} €
                          </a>
                        ) : (
                          `${v.price.toFixed(2).replace(".", ",")} €`
                        )
                      ) : (
                        <span className="compare-na">—</span>
                      )}
                    </td>
                  );
                })}
                <td className="compare-winner">
                  <span
                    className="vendor-badge"
                    style={{
                      background: OPERATOR_BADGE[best.operator]?.color ?? "#666",
                    }}
                  >
                    {OPERATOR_BADGE[best.operator]?.label ?? best.operator}
                  </span>{" "}
                  {best.price.toFixed(2).replace(".", ",")} €
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
