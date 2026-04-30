import { useState } from "react";
import { Phone } from "../api";
import { OPERATOR_BADGE } from "../operatorColors";
import { PriceHistoryChart } from "./PriceHistoryChart";

interface Props {
  phone: Phone;
}

const PLACEHOLDER = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='90' viewBox='0 0 80 90'%3E%3Crect width='80' height='90' fill='%23f0f0f0' rx='8'/%3E%3Ctext x='50%25' y='55%25' text-anchor='middle' fill='%23bbb' font-size='11' font-family='sans-serif'%3ESans image%3C/text%3E%3C/svg%3E";

export function PhoneCard({ phone }: Props) {
  const [showHistory, setShowHistory] = useState(false);
  const snap = phone.latest_snapshot;

  const formatPrice = (p: number | null | undefined) =>
    p != null ? `${p.toFixed(2).replace(".", ",")} €` : "–";

  const abbrevPlan = (name: string) =>
    name
      .replace("Forfait ", "")
      .replace("entrée de gamme", "EDG")
      .replace("haut de gamme", "HDG")
      .replace("client SFR mobile", "SFR mobile")
      .replace("client SFR Box", "SFR Box")
      .replace(" mois", "m")
      .replace(/\s*–\s*/g, " · ");

  return (
    <div className="phone-card">
      <div className="phone-card-img-wrap">
        {phone.is_refurbished && (
          <span className="refurbished-badge">Reconditionné</span>
        )}
        <img
          src={phone.image_url ?? PLACEHOLDER}
          alt={phone.name}
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).src = PLACEHOLDER;
          }}
        />
      </div>
      <div className="phone-card-body">
        <div className="phone-brand-row">
          <p className="phone-brand">{phone.brand}</p>
          <span
            className="vendor-badge"
            style={{ background: OPERATOR_BADGE[phone.operator]?.color ?? "#666" }}
          >
            {OPERATOR_BADGE[phone.operator]?.label ?? phone.operator}
          </span>
        </div>
        <h3 className="phone-name">{phone.model}</h3>
        {(phone.storage || phone.color) && (
          <p className="phone-meta">
            {[phone.storage, phone.color].filter(Boolean).join(" · ")}
          </p>
        )}

        {snap ? (
          <>
            <p className="phone-price-nu">
              Prix nu : <strong>{formatPrice(snap.price_nu)}</strong>
            </p>

            {snap.promotion && (
              <p className="phone-promo">🏷 {snap.promotion}</p>
            )}

            {snap.plan_prices.length > 0 && (
              <table className="plan-table">
                <thead>
                  <tr>
                    <th>Prix terminal</th>
                    <th>Forfait</th>
                  </tr>
                </thead>
                <tbody>
                  {snap.plan_prices.map((pp, i) => (
                    <tr key={i}>
                      <td><strong>{formatPrice(pp.price_device)}</strong></td>
                      <td>{abbrevPlan(pp.plan_name)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <p className="snap-date">
              Collecté le {new Date(snap.scraped_at).toLocaleString("fr-FR")}
            </p>
          </>
        ) : (
          <p className="no-data">Pas encore de données</p>
        )}

        <button
          className="history-btn"
          onClick={() => setShowHistory(!showHistory)}
        >
          {showHistory ? "Masquer l'historique" : "Voir l'historique des prix"}
        </button>

        {showHistory && <PriceHistoryChart phoneId={phone.id} />}
      </div>
    </div>
  );
}
