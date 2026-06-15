# Plan your trip with Kayak

Projet de certification Jedha — module *Data Collection & Management*.

Pipeline de données complet pour recommander les meilleures destinations de voyage en France, à partir de données météo temps réel et d'informations hôtelières extraites de Booking.com.

## Architecture

```
Nominatim API   ──┐
                  ├──► projet-kayak.ipynb ──► PostgreSQL (cities, weather_cities)
Open-Meteo API  ──┘

Booking.com ──► playwright-booking.py ──► S3 (hotels/)
                        ▲                        │
                  Top-5 depuis DB         transform.ipynb
                                                 │
                                    S3 (CSV) + PostgreSQL (hotels_enriched)
                                                 │
                                         visualisation.ipynb
```

## Stack

| Couche | Outils |
|---|---|
| Collecte web | Playwright |
| APIs | Nominatim (géocodage), Open-Meteo (météo) |
| Stockage | AWS S3, AWS RDS PostgreSQL |
| Traitement | Pandas, SQLAlchemy |
| Visualisation | Plotly Express |

## Structure

```
├── config/
│   └── cities.json             # Liste des 35 villes
├── projet-kayak.ipynb          # Géocodage + météo → DB
├── playwright-booking.py       # Scraping Booking.com → S3
├── transform.ipynb             # ETL : S3 → nettoyage → S3 (CSV) + DB
├── visualisation.ipynb         # Cartes Top-5 villes et Top-20 hôtels
├── parse_hotels.ipynb          # Exploration des données hôtels (hors pipeline)
├── sql/                        # DDL des tables
└── outputs/                    # Fichiers locaux (non versionnés)
```

## Données collectées

- **35 villes** françaises géocodées via Nominatim
- **Météo 7 jours** par ville : weather code WMO, températures min/max, précipitations
- **hôtels** sur Booking.com : nom, description, score, nombre d'avis, coordonnées GPS

## Indicateur météo

Le classement des destinations repose sur le `weather_code` Open-Meteo (norme WMO : 0 = ciel dégagé, valeurs croissantes vers les intempéries). Il est normalisé sur une échelle 0–10 et moyenné sur la semaine pour chaque ville.

## Configuration

Copier `.env.example` en `.env` :

```env
USER_AGENT=
AWS_ACCESS_KEY=
AWS_SECRET_KEY=
AWS_REGION=
AWS_BUCKET=
AWS_BUCKET_DIR=
DB_USER=
DB_PASSWORD=
DB_HOST=
DB_NAME=
```

## Lancement

```bash
pip install -r requirements.txt
playwright install chromium
```

Ordre d'exécution :
1. `projet-kayak.ipynb` — géocodage et météo → DB
2. `playwright-booking.py` — scraping des hôtels → S3
3. `transform.ipynb` — ETL hôtels → S3 (CSV) + DB
4. `visualisation.ipynb` — cartes et classements
