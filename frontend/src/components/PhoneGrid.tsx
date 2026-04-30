import { useMemo, useState } from "react";
import { Phone } from "../api";
import { PhoneCard } from "./PhoneCard";
import { PriceCompare } from "./PriceCompare";

interface Props {
  phones: Phone[];
  brands: string[];
}

export function PhoneGrid({ phones, brands }: Props) {
  const [selectedBrand, setSelectedBrand] = useState<string>("");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<"name" | "price_asc" | "price_desc">("name");
  const [viewMode, setViewMode] = useState<"grid" | "compare">("grid");

  const filtered = useMemo(() => {
    let list = phones;
    if (selectedBrand) {
      list = list.filter((p) => p.brand.toLowerCase() === selectedBrand.toLowerCase());
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter((p) => p.name.toLowerCase().includes(q));
    }
    return [...list].sort((a, b) => {
      if (sortBy === "name") return a.name.localeCompare(b.name);
      const pa = a.latest_snapshot?.price_nu ?? Infinity;
      const pb = b.latest_snapshot?.price_nu ?? Infinity;
      return sortBy === "price_asc" ? pa - pb : pb - pa;
    });
  }, [phones, selectedBrand, search, sortBy]);

  const canCompare = search.trim().length > 0 && filtered.length > 0;

  return (
    <div className="phone-grid-wrapper">
      <div className="filters">
        <input
          type="search"
          placeholder="Rechercher un modèle…"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            if (!e.target.value.trim()) setViewMode("grid");
          }}
          className="search-input"
        />

        <select
          value={selectedBrand}
          onChange={(e) => setSelectedBrand(e.target.value)}
          className="brand-select"
        >
          <option value="">Toutes les marques</option>
          {brands.map((b) => (
            <option key={b} value={b}>{b}</option>
          ))}
        </select>

        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
          className="sort-select"
        >
          <option value="name">Trier par nom</option>
          <option value="price_asc">Prix croissant</option>
          <option value="price_desc">Prix décroissant</option>
        </select>

        {canCompare && (
          <button
            className={`compare-toggle ${viewMode === "compare" ? "active" : ""}`}
            onClick={() => setViewMode(viewMode === "grid" ? "compare" : "grid")}
            title="Comparer les prix entre revendeurs"
          >
            {viewMode === "compare" ? "⊞ Grille" : "⇔ Comparateur"}
          </button>
        )}

        <span className="result-count">{filtered.length > 1 ? `${filtered.length} terminaux` : `${filtered.length} terminal`}</span>
      </div>

      {filtered.length === 0 ? (
        <p className="no-data" style={{ padding: "2rem" }}>
          Aucun terminal trouvé. Lancez une collecte pour alimenter le catalogue.
        </p>
      ) : viewMode === "compare" ? (
        <PriceCompare phones={filtered} />
      ) : (
        <div className="phone-grid">
          {filtered.map((phone) => (
            <PhoneCard key={phone.id} phone={phone} />
          ))}
        </div>
      )}
    </div>
  );
}
