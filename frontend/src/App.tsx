import { useCallback, useEffect, useState } from "react";
import { api, Operator, Phone } from "./api";
import { PhoneGrid } from "./components/PhoneGrid";
import { ScrapeButton } from "./components/ScrapeButton";

export default function App() {
  const [phones, setPhones] = useState<Phone[]>([]);
  const [brands, setBrands] = useState<string[]>([]);
  const [operators, setOperators] = useState<Operator[]>([]);
  const [selectedOperator, setSelectedOperator] = useState<string>("");
  const [productType, setProductType] = useState<string>("phone");
  const [showRefurbished, setShowRefurbished] = useState<string>("");
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

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-content">
          <div className="header-title">
            <h1>Veille Tarifaire Terminaux</h1>
            <div className="operator-tabs">
              <button
                className={!selectedOperator ? "active" : ""}
                onClick={() => setSelectedOperator("")}
              >
                Tous
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
          </div>
          <ScrapeButton onScrapeComplete={loadData} operators={operators} />
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
          <PhoneGrid phones={phones} brands={brands} />
        )}
      </main>

      <footer className="app-footer">
        <p>
          {phones.length > 1 ? `${phones.length} terminaux` : `${phones.length} terminal`} en base
          {selectedOperator
            ? ` · ${operators.find((o) => o.id === selectedOperator)?.label ?? selectedOperator}`
            : " · Tous vendeurs"}
        </p>
      </footer>
    </div>
  );
}
