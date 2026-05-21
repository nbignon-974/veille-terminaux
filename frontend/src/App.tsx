import { useCallback, useEffect, useMemo, useState } from "react";
import { api, Operator, Phone } from "./api";
import { PhoneGrid } from "./components/PhoneGrid";
import { ScrapeButton } from "./components/ScrapeButton";

type PriceRange = "" | "0-200" | "200-500" | "500-1000" | "1000+";

const PRICE_RANGES: { key: PriceRange; label: string }[] = [
  { key: "", label: "Tous prix" },
  { key: "0-200", label: "< 200 €" },
  { key: "200-500", label: "200 – 500 €" },
  { key: "500-1000", label: "500 – 1000 €" },
  { key: "1000+", label: "> 1000 €" },
];

function inPriceRange(phone: Phone, range: PriceRange): boolean {
  if (!range) return true;
  const price = phone.latest_snapshot?.price_nu;
  if (price == null) return false;
  if (range === "0-200") return price < 200;
  if (range === "200-500") return price >= 200 && price < 500;
  if (range === "500-1000") return price >= 500 && price < 1000;
  if (range === "1000+") return price >= 1000;
  return true;
}

export default function App() {
  const [phones, setPhones] = useState<Phone[]>([]);
  const [brands, setBrands] = useState<string[]>([]);
  const [operators, setOperators] = useState<Operator[]>([]);
  const [selectedOperator, setSelectedOperator] = useState<string>("");
  const [productType, setProductType] = useState<string>("phone");
  const [showRefurbished, setShowRefurbished] = useState<string>("");
  const [priceRange, setPriceRange] = useState<PriceRange>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getOperators().then(setOperators).catch(() => {});
  }, []);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const op = selectedOperator || undefined;
      const pt = productType || undefined;
      const isRef = showRefurbished === "yes" ? true : showRefurbished === "no" ? false : undefined;
      const [phonesData, brandsData] = await Promise.all([
        api.getPhones(undefined, undefined, op, pt, isRef),
        api.getBrands(op),
      ]);
      setPhones(phonesData);
      setBrands(brandsData);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [selectedOperator, productType, showRefurbished]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const filteredPhones = useMemo(
    () => phones.filter((p) => inPriceRange(p, priceRange)),
    [phones, priceRange]
  );

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-content">
          <div className="header-top">
            <h1>Veille Tarifaire Terminaux</h1>
            <ScrapeButton onScrapeComplete={loadData} operators={operators} />
          </div>
          <div className="header-separator" />
          <div className="header-title">
            <div className="operator-tabs">
              <button
                className={!selectedOperator ? "active" : ""}
                onClick={() => setSelectedOperator("")}
              >
                Tous vendeurs
              </button>
              {operators.map((op) => (
                <button
                  key={op.id}
                  className={selectedOperator === op.id ? "active" : ""}
                  onClick={() => setSelectedOperator(op.id)}
                >
                  {op.label}
                </button>
              ))}
            </div>
            <div className="product-type-tabs">
              <button
                className={productType === "phone" ? "active" : ""}
                onClick={() => setProductType("phone")}
              >
                Terminaux
              </button>
              <button
                className={productType === "accessory" ? "active" : ""}
                onClick={() => setProductType("accessory")}
              >
                Accessoires
              </button>
              <button
                className={!productType ? "active" : ""}
                onClick={() => setProductType("")}
              >
                Tout
              </button>
            </div>
            <div className="product-type-tabs">
              <button
                className={showRefurbished === "" ? "active" : ""}
                onClick={() => setShowRefurbished("")}
              >
                Tous états
              </button>
              <button
                className={showRefurbished === "no" ? "active" : ""}
                onClick={() => setShowRefurbished("no")}
              >
                Neuf
              </button>
              <button
                className={showRefurbished === "yes" ? "active" : ""}
                onClick={() => setShowRefurbished("yes")}
              >
                Reconditionné
              </button>
            </div>
            <div className="product-type-tabs">
              {PRICE_RANGES.map(({ key, label }) => (
                <button
                  key={key}
                  className={priceRange === key ? "active" : ""}
                  onClick={() => setPriceRange(key)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </header>

      <main className="app-main">
        {loading && (
          <div className="loading-state">
            <div className="spinner" />
            <p>Chargement du catalogue…</p>
          </div>
        )}

        {error && !loading && (
          <div className="error-state">
            <p>Erreur lors du chargement : {error}</p>
            <button onClick={loadData} className="retry-btn">Réessayer</button>
          </div>
        )}

        {!error && (
          <PhoneGrid phones={filteredPhones} brands={brands} />
        )}
      </main>

      <footer className="app-footer">
        <p>
          {filteredPhones.length > 1 ? `${filteredPhones.length} terminaux` : `${filteredPhones.length} terminal`} en base
          {selectedOperator
            ? ` · ${operators.find((o) => o.id === selectedOperator)?.label ?? selectedOperator}`
            : " · Tous vendeurs"}
        </p>
      </footer>
    </div>
  );
}
