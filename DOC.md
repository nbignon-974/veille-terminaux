# Veille Terminaux — Documentation technique

## Vue d'ensemble

Outil de veille tarifaire multi-opérateurs pour les smartphones commercialisés à La Réunion.  
L'application scrape périodiquement les catalogues en ligne de 10 vendeurs, stocke l'historique des prix et propose une interface web de consultation avec filtres, recherche, graphiques d'évolution et comparateur de prix inter-vendeurs.

---

## Stack technique

| Couche    | Technologie                                  | Version  |
|-----------|----------------------------------------------|----------|
| Backend   | Python / FastAPI / Uvicorn                   | 3.9 / 0.115 / 0.32 |
| ORM       | SQLAlchemy                                   | 2.0      |
| Base      | SQLite (fichier local `veille_terminaux.db`) | —        |
| Scraping  | Playwright (Chromium headless)               | 1.49     |
| Frontend  | React / TypeScript / Vite                    | 18 / 5.7 / 6.0 |
| Graphiques| Recharts                                     | 2.13     |

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Frontend  (localhost:5173)                               │
│  React + TypeScript + Recharts                           │
│  Vite dev proxy → /phones, /scrape, /brands, /operators  │
└──────────────────┬───────────────────────────────────────┘
                   │  REST JSON
┌──────────────────▼───────────────────────────────────────┐
│  Backend  (localhost:8000)                                │
│  FastAPI + Uvicorn --reload                              │
│                                                          │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  Scrapers (Playwright headless)                     │ │
│  │  sfr_re │ zeop │ smartshop │ phenix │ leclic │      │ │
│  │  bvallee │ ravate │ infinytech │ distripc │ darty  │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                          │
│  SQLAlchemy ──► SQLite (veille_terminaux.db)             │
└──────────────────────────────────────────────────────────┘
```

---

## Opérateurs intégrés

| Clé         | Vendeur           | Source                                        | Type de prix                       |
|-------------|-------------------|-----------------------------------------------|------------------------------------|
| `sfr_re`    | SFR Réunion       | API REST JSON interne (iframe AngularJS)      | Nu + forfaits (12/24 mois, mobile/box) |
| `zeop`      | Zeop Store        | HTML scraping (pagination serveur)            | Prix nu uniquement                 |
| `smartshop` | SmartShop         | PrestaShop — `article.js-product-miniature`   | Prix nu + promos                   |
| `phenix`    | Phenix Store      | PrestaShop — `data-id-product`                | Prix nu + promos                   |
| `leclic`    | Leclic.re         | PrestaShop — HTML scraping                    | Prix nu + promos                   |
| `bvallee`   | Bureau Vallée     | HTML scraping — `.c-productCard` (pagination) | Prix nu uniquement                 |
| `ravate`    | Ravate            | PrestaShop — infinite scroll (`.product-card`)| Prix nu + promos                   |
| `infinytech` | Infinytech       | CMS cdnws — pagination (`article.prod__article`) | Prix nu + promos                |
| `distripc`  | DistriPC          | Algolia — pagination (`?prod_distripc[page]=N`)  | Prix nu + promos                |
| `darty`     | Darty Réunion     | HTML scraping — GTM data attributes (pagination serveur) | Prix nu uniquement              |

---

## Modèle de données

```
Phone  ←1:N→  PriceSnapshot  ←1:N→  PlanPrice
                    ↑
               ScrapeRun (1 run = 1 opérateur)
```

### Phone
| Colonne         | Type    | Description                          |
|-----------------|---------|--------------------------------------|
| `sfr_id`        | String  | ID produit chez le vendeur           |
| `name`          | String  | Nom complet du produit               |
| `brand`         | String  | Marque (Apple, Samsung…)             |
| `model`         | String  | Modèle (iPhone 16, Galaxy S25…)      |
| `storage`       | String  | Stockage (128GO, 256GO…)             |
| `color`         | String  | Coloris                              |
| `operator`      | String  | Clé opérateur (sfr_re, zeop…)        |
| `product_type`  | String  | `phone` ou `accessory`               |
| `is_refurbished`| Integer | 1 si reconditionné, 0 sinon          |
| `image_url`     | String  | URL de la photo produit              |
| `page_url`      | String  | URL de la fiche produit              |

Contrainte unique : `(sfr_id, operator)`

### PriceSnapshot
Capture un prix à un instant t : `price_nu`, `promotion`, `available`, `scraped_at`.

### PlanPrice
Détail forfait (SFR uniquement) : `plan_name`, `price_monthly`, `price_device`, `engagement_months`.

### ScrapeRun
Journal d'exécution : `operator`, `status` (pending/running/done/error), `phones_found`, `phones_scraped`, timestamps.

---

## Classification automatique

### Type de produit (`phone` / `accessory`)
La fonction `classify_product(brand, name)` dans `scrapers.py` :
1. Détecte les **mots-clés accessoires** dans le nom : watch, montre, airpods, buds, chargeur, câble, coque, tablette, galaxy tab, caméra, etc.
2. Vérifie si la marque est dans `PHONE_BRANDS` (Apple, Samsung, Xiaomi, Honor, etc.)
3. Détecte les noms commençant par "iPhone" ou "Smartphone" comme téléphones

### Détection reconditionnés
La fonction `detect_refurbished(name, url)` identifie les produits reconditionnés via :
- Mots-clés dans le nom : `reconditionné`, `REC`, `grade A`, `renewed`, `refurb`, `occasion`
- URL contenant `/reconditionne/`

---

## Endpoints API

| Méthode | Route                  | Description                                      |
|---------|------------------------|--------------------------------------------------|
| GET     | `/phones`              | Liste des téléphones (filtres: brand, search, operator, product_type, is_refurbished) |
| GET     | `/phones/{id}/history` | Historique des prix d'un téléphone               |
| POST    | `/scrape?operator=`    | Lancer un scrape (tâche de fond)                 |
| GET     | `/scrape/runs`         | 50 dernières exécutions                          |
| GET     | `/scrape/{run_id}`     | Statut + progression temps réel d'un scrape      |
| GET     | `/brands`              | Liste des marques (filtre operator optionnel)     |
| GET     | `/operators`           | Liste des opérateurs disponibles                 |

---

## Frontend

### Filtres et navigation
- **Onglets opérateurs** : Tous · SFR · Zeop · SmartShop · Phenix · Leclic · Bureau Vallée · Ravate · Infinytech · DistriPC · Darty
- **Onglets type produit** : Terminaux · Accessoires · Tout
- **Onglets état** : Tous états · Neuf · Reconditionné
- **Grille produits** : Recherche texte, filtre par marque, tri par prix

### Composants
- **Cartes produit** : Photo, prix, badge opérateur coloré, badge reconditionné (violet), indicateur promo
- **Comparateur de prix** : Vue BarChart Recharts regroupant les prix par modèle entre vendeurs (activé depuis la recherche)
- **Graphique d'historique** : Courbe Recharts (prix nu + forfaits abrégés)
- **Bouton scrape** : Sélection opérateur, lancement, suivi en temps réel

### Badges opérateurs
| Opérateur      | Couleur   |
|----------------|-----------|
| SFR            | `#e2001a` rouge   |
| Zeop           | `#7b2d8e` violet  |
| SmartShop      | `#00b4d8` bleu    |
| Phenix         | `#e85d04` orange  |
| Leclic         | `#00a651` vert    |
| Bureau Vallée  | `#003da5` bleu    |
| Ravate         | `#d4213d` rouge   |
| Infinytech     | `#00b0f0` bleu    |
| DistriPC       | `#ff6f00` orange  |
| Darty          | `#ce0e2d` rouge   |

---

## Arborescence du projet

```
backend/
├── main.py              # App FastAPI, endpoints, tâche de scrape, migrations
├── models.py            # Modèles SQLAlchemy (Phone, PriceSnapshot, PlanPrice, ScrapeRun)
├── database.py          # Connexion SQLite, session factory
├── scrapers.py          # Registre opérateurs, types communs, classify_product(), detect_refurbished(), persist_results()
├── scraper_sfr.py       # Scraper SFR Réunion (API JSON)
├── scraper_zeop.py      # Scraper Zeop Store (HTML, pagination serveur)
├── scraper_smartshop.py # Scraper SmartShop (PrestaShop)
├── scraper_phenix.py    # Scraper Phenix Store (PrestaShop)
├── scraper_leclic.py    # Scraper Leclic.re (PrestaShop)
├── scraper_bvallee.py   # Scraper Bureau Vallée (HTML, pagination ?p=N)
├── scraper_ravate.py    # Scraper Ravate (PrestaShop, infinite scroll)
├── scraper_infinytech.py # Scraper Infinytech Réunion (CMS cdnws, pagination)
├── scraper_distripc.py  # Scraper DistriPC (Algolia, pagination ?prod_distripc[page]=N)
├── scraper_darty.py     # Scraper Darty Réunion (HTML, GTM data attributes, pagination serveur)
├── requirements.txt     # Dépendances Python
└── veille_terminaux.db  # Base SQLite

frontend/src/
├── App.tsx              # Composant principal, état, onglets filtres
├── api.ts               # Client API TypeScript
├── operatorColors.ts    # Couleurs et labels des badges opérateurs
├── index.css            # Thème orange (#ff7900)
├── main.tsx             # Point d'entrée React
└── components/
    ├── PhoneCard.tsx          # Carte produit + badge opérateur + badge reconditionné
    ├── PhoneGrid.tsx          # Grille filtrable/triable + bascule comparateur
    ├── PriceCompare.tsx       # Comparateur de prix inter-vendeurs (BarChart)
    ├── PriceHistoryChart.tsx  # Graphique historique Recharts
    └── ScrapeButton.tsx       # Contrôle de scrape

start.sh                 # Lance backend + frontend en parallèle
```

---

## Lancement

```bash
./start.sh
# ou manuellement :
cd backend && ../.venv/bin/uvicorn main:app --reload --port 8000
cd frontend && npm run dev
```

- Backend : http://localhost:8000
- Frontend : http://localhost:5173

---

## Volumes de données constatés

| Opérateur       | Total | Phones | Accessoires | Reconditionnés |
|-----------------|-------|--------|-------------|----------------|
| SFR Réunion     | ~147  | 147    | —           | 5              |
| Zeop Store      | ~125  | 25     | 100         | —              |
| SmartShop       | ~152  | 152    | —           | —              |
| Phenix Store    | ~112  | 112    | —           | 17             |
| Leclic.re       | ~47   | 42     | 5           | 2              |
| Bureau Vallée   | ~12   | 12     | —           | —              |
| Ravate          | ~490  | 205    | 285         | 94             |
| Infinytech      | ~103  | 72     | 31          | —              |
| DistriPC        | ~100  | 54     | 46          | —              |
| Darty Réunion   | ~86   | 86     | —           | —              |
| **Total**       | **~1374** | **907** | **467** | **118**        |
