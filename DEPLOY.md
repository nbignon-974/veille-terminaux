# Plan de déploiement — Veille Terminaux

Déploiement de la solution sur **Render** (backend Docker), **Neon** (PostgreSQL serverless) et **Netlify** (frontend statique), avec CI/CD automatique via **GitHub** (branche `main`).

---

## Prérequis

- Compte [GitHub](https://github.com) avec le repo `veille-terminaux` poussé sur la branche `main`
- Compte [Neon](https://neon.tech) (plan free : 3 Go DB, pas de limite d'egress séparée)
- Compte [Render](https://render.com) (plan free : 750h/mois, cold start ~30s après 15 min d'inactivité)
- Compte [Netlify](https://netlify.com) (plan free : 100 Go bandwidth + 300 build min/mois)

---

## Phase 1 — Base de données PostgreSQL sur Neon

Le stockage SQLite est éphémère sur Render : toutes les données sont perdues à chaque redéploiement. On utilise donc un PostgreSQL managé. Neon est privilégié au plan free de Supabase car (1) il ne pause pas le projet après 7 jours d'inactivité (juste un autosuspend qui résume en <1s), (2) il n'a pas de limite d'egress mensuelle séparée susceptible de saturer rapidement, et (3) il offre 3 Go de stockage.

1. Neon Console → **New Project**
2. Renseigner :
   - **Name** : `veille-terminaux`
   - **Postgres version** : 17 (par défaut)
   - **Region** : **Europe (Frankfurt)** — à aligner avec le service backend Render
3. Cliquer sur **Create project**
4. Sur l'écran "Connection Details", copier la **Direct connection** (pas pooled — voir note ci-dessous). Format :
   ```
   postgresql://neondb_owner:xxx@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=require
   ```

> 💡 Neon expose 2 endpoints : direct (`ep-xxx.neon.tech`) et pooled (`ep-xxx-pooler.neon.tech`). Pour FastAPI/SQLAlchemy single-worker, l'endpoint **direct** est préférable — il évite les surprises liées au mode transaction de PgBouncer (server-side cursors, `LISTEN/NOTIFY`, advisory locks ne fonctionnent pas via le pooler).

---

## Phase 2 — Backend sur Render

Le backend est déployé via Docker. Le fichier `render.yaml` à la racine du repo configure le service automatiquement.

1. Render Dashboard → **New** → **Web Service**
2. Cliquer sur **Connect a repository** → autoriser l'accès GitHub → sélectionner `veille-terminaux`
3. Render détecte automatiquement le `render.yaml`. Vérifier les paramètres :
   - **Name** : `veille-terminaux-backend`
   - **Branch** : `main`
   - **Runtime** : Docker
   - **Dockerfile Path** : `./backend/Dockerfile`
   - **Plan** : Free
4. Dans la section **Environment Variables**, ajouter manuellement :

   | Clé | Valeur |
   |-----|--------|
   | `DATABASE_URL` | Connection string Neon copiée en Phase 1 (endpoint direct, avec `?sslmode=require`) |
   | `ALLOWED_ORIGINS` | *(à compléter après Phase 3, ex : `https://veille-terminaux.netlify.app`)* |

5. Cliquer sur **Create Web Service**
6. Render lance le build Docker. **Le premier build peut prendre ~10 minutes** (l'image Playwright pèse environ 2 Go).
7. Une fois déployé, copier l'URL publique du service (ex : `https://veille-terminaux-backend.onrender.com`). Elle sera nécessaire en Phase 3.

> ⚠️ Sur le plan gratuit, le service Render **se met en veille après 15 minutes d'inactivité**. La première requête après une période de veille prend environ 30 secondes (cold start).

---

## Phase 3 — Frontend sur Netlify

Le frontend est un build Vite statique. Le fichier `netlify.toml` à la racine du repo configure le build et les redirections SPA automatiquement.

1. Netlify → **Add new site** → **Import an existing project**
2. Cliquer sur **Deploy with GitHub** → autoriser l'accès → sélectionner `veille-terminaux`
3. Netlify détecte automatiquement le `netlify.toml`. Vérifier les paramètres :
   - **Branch to deploy** : `main`
   - **Build command** : `cd frontend && npm install && npm run build`
   - **Publish directory** : `frontend/dist`
4. Dans la section **Environment variables**, ajouter :

   | Clé | Valeur |
   |-----|--------|
   | `VITE_API_URL` | URL du backend Render copiée en Phase 2 (ex : `https://veille-terminaux-backend.onrender.com`) |

5. Cliquer sur **Deploy site**
6. Une fois déployé, copier l'URL générée par Netlify (ex : `https://veille-terminaux.netlify.app`).

> 💡 Vous pouvez personnaliser le sous-domaine Netlify dans **Site configuration → Domain management**.

---

## Phase 4 — Finalisation CORS

Le backend refuse les requêtes provenant d'origines non autorisées. Il faut mettre à jour la variable `ALLOWED_ORIGINS` avec l'URL Netlify définitive.

1. Render Dashboard → service `veille-terminaux-backend` → **Environment**
2. Mettre à jour la variable :

   | Clé | Valeur |
   |-----|--------|
   | `ALLOWED_ORIGINS` | URL Netlify exacte, **sans slash final** (ex : `https://veille-terminaux.netlify.app`) |

3. Render redéploie automatiquement le service après la modification.
4. Vérifier que le frontend peut interroger le backend sans erreur CORS depuis le navigateur.

---

## Phase 5 — CI/CD automatique

Une fois les deux services connectés à GitHub, tout push sur la branche `main` déclenche automatiquement :

- Un **redéploiement du frontend** sur Netlify (build Vite + publication)
- Un **redéploiement du backend** sur Render (build Docker + restart)

Il n'y a aucune configuration supplémentaire à faire.

---

## Récapitulatif des variables d'environnement

| Service | Variable | Description |
|---------|----------|-------------|
| Render (backend) | `DATABASE_URL` | Connection string PostgreSQL Neon (endpoint direct, `?sslmode=require`) |
| Render (backend) | `ALLOWED_ORIGINS` | URL du frontend Netlify (sans slash final) |
| Netlify (frontend) | `VITE_API_URL` | URL publique du backend Render |

---

## Points d'attention

| Sujet | Détail |
|-------|--------|
| **Base de données** | Ne jamais utiliser SQLite en production sur Render — le stockage est réinitialisé à chaque déploiement |
| **Neon autosuspend** | La DB Neon se met en veille après ~5 min d'inactivité, mais résume en <1s à la première requête (transparent côté backend) |
| **Pooler vs direct** | Toujours utiliser l'endpoint direct Neon dans `DATABASE_URL` — le pooler casse certaines features SQLAlchemy |
| **Cold start** | Le plan gratuit Render met le service en veille après 15 min. Prévoir un délai de ~30s sur la première requête |
| **Build Docker** | L'image Microsoft Playwright (~2 Go) rend le premier build lent (~10 min). Les builds suivants utilisent le cache |
| **CORS** | `ALLOWED_ORIGINS` doit correspondre **exactement** à l'URL Netlify — sans slash final, avec le protocole `https://` |
| **Variables Vite** | Les variables d'environnement Netlify préfixées `VITE_` sont injectées au moment du build, pas à l'exécution |
