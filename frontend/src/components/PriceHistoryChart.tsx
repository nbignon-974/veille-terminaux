import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, Snapshot } from "../api";

interface Props {
  phoneId: number;
}

const PLAN_COLORS = [
  "#e63946",
  "#2196F3",
  "#4CAF50",
  "#FF9800",
  "#9C27B0",
  "#00BCD4",
];

function shortPlanName(name: string): string {
  const gamme = /haut de gamme/i.test(name) ? "HDG" : "EDG";
  const client = /box/i.test(name) ? "Box" : "Mobile";
  const months = name.match(/(\d+)\s*mois/i);
  const dur = months ? `${months[1]}m` : "";
  return `${gamme} · ${client} · ${dur}`;
}

export function PriceHistoryChart({ phoneId }: Props) {
  const [history, setHistory] = useState<Snapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    api
      .getPhoneHistory(phoneId)
      .then(setHistory)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [phoneId]);

  if (loading) return <p className="chart-loading">Chargement…</p>;
  if (error) return <p className="error-msg">{error}</p>;
  if (history.length === 0) return <p className="no-data">Pas encore d'historique.</p>;

  // Collect all unique plan names across history
  const planNames = Array.from(
    new Set(history.flatMap((s) => s.plan_prices.map((pp) => pp.plan_name)))
  );

  // Build chart data: one entry per snapshot date, using short plan names
  const shortNames = Object.fromEntries(planNames.map((p) => [p, shortPlanName(p)]));

  const chartData = history.map((snap) => {
    const planMap: Record<string, number | null> = {};
    for (const pp of snap.plan_prices) {
      planMap[shortNames[pp.plan_name]] = pp.price_monthly ?? null;
    }
    return {
      date: new Date(snap.scraped_at).toLocaleDateString("fr-FR"),
      price_nu: snap.price_nu,
      ...planMap,
    };
  });

  const shortPlanKeys = planNames.map((p) => shortNames[p]);
  const uniqueShortKeys = Array.from(new Set(shortPlanKeys));

  return (
    <div className="history-chart">
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} />
          <YAxis
            tickFormatter={(v) => `${v}€`}
            tick={{ fontSize: 11 }}
            width={52}
          />
          <Tooltip formatter={(value: number) => `${value.toFixed(2)}€`} />
          <Legend
            verticalAlign="bottom"
            wrapperStyle={{ fontSize: "0.7rem", lineHeight: "1.4", paddingTop: 8 }}
          />

          <Line
            type="monotone"
            dataKey="price_nu"
            name="Prix nu"
            stroke="#333"
            strokeWidth={2}
            dot={{ r: 3 }}
            connectNulls
          />

          {uniqueShortKeys.map((shortName, i) => (
            <Line
              key={shortName}
              type="monotone"
              dataKey={shortName}
              name={shortName}
              stroke={PLAN_COLORS[i % PLAN_COLORS.length]}
              strokeWidth={1.5}
              strokeDasharray="4 2"
              dot={{ r: 2 }}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
