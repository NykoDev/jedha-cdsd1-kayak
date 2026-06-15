# test_booking.py
# initialisation
from dotenv import load_dotenv
import sys
import os
import pandas as pd
import boto3
import time
import asyncio
import json
from datetime import date
from playwright.async_api import async_playwright
from sqlalchemy import create_engine

# chargement user agent depuis le fichier .env
load_dotenv()
USER_AGENT = os.getenv("USER_AGENT")
AWS_WAF_TOKEN = os.getenv("AWS_WAF_TOKEN")
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")
AWS_BUCKET = os.getenv("AWS_BUCKET")
AWS_BUCKET_DIR = os.getenv("AWS_BUCKET_DIR")

DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
engine = create_engine(f"postgresql+psycopg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}")

LOCAL_DIR = "./outputs/hotels/"
HOTEL_INFOS_FILENAME = "hotels_infos.json"
HOTEL_LOCATIONS_FILENAME = "hotels_locations.json"

today = date.today()

s3_client = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name="eu-west-3",
)

try:
    df_top = pd.read_sql(
        """SELECT c.city_id, c.city, c.latitude, c.longitude, wc.weather_code_mean
           FROM weather_cities wc
           JOIN cities c ON wc.city_id = c.city_id
           WHERE wc.date = %(d)s
           ORDER BY wc.weather_code_mean
           LIMIT 5""",
        engine, params={"d": today}
    )

    if df_top.empty:
        raise ValueError("Aucune donnée météo pour aujourd'hui. Lancer projet-kayak.ipynb d'abord.")
    top_cities = df_top.to_dict(orient='records')
    print(top_cities)
except Exception as e:
    raise RuntimeError(f"Erreur lecture DB: {e}")


# scrapper en mode asynchrone
async def scraper_booking(list_cities):
    async with async_playwright() as p:

        # lancement navigateur
        browser = await p.chromium.launch(
            headless=False,
        )

        # configuration du contexte (headers)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={'width': 1920, 'height': 1080},
            extra_http_headers={
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8'
            }
        )

        # ajout du cookie aws waf (protection anti-bot)
        await context.add_cookies([{
            'name': 'aws-waf-token',
            'value': AWS_WAF_TOKEN,
            'domain': '.booking.com',
            'path': '/'
        }])

        all_hotels_infos = []
        all_hotels_locations = []

        for city_raw in list_cities:

            if 'city' not in city_raw or 'city_id' not in city_raw:
                continue

            city = city_raw['city']
            city_id = city_raw['city_id']
            
            sanitize_city = city.lower().replace(' ', '_')

            hotels_infos_filename = f'hotels_infos_{sanitize_city}.json'
            hotels_location_filename = f'hotels_location_{sanitize_city}.json'

            # accès direct à la page de recherche en attendant le chargement complet de tous les elements (js compris)
            page = await context.new_page()
            response = await page.goto(f"https://www.booking.com/searchresults.fr.html?ss={city}", wait_until='networkidle')

            try:
                await page.keyboard.press('Escape')
                await page.wait_for_timeout(500)
            except:
                pass

            # filtre par hotel
            # clic sur le conteneur car l'élément input check n'est pas visible
            filter_item = page.locator('div[data-filters-item="popular:ht_id=204"]')
            await filter_item.click(force=True)
            await page.wait_for_timeout(3000)

            #récupération données hotels
            hotels_infos = list()
            hotel_items = await page.locator('div[data-testid="property-card"]').all()

            for hotel in hotel_items:
                try:
                    hotel_infos = {
                        'city_id': city_id,
                        'city': city
                    }
                    #nom hotel
                    hotel_infos['name'] = await hotel.locator('div[data-testid="title"]').text_content()
                    print(hotel_infos['name'])
                    #description
                    hotel_infos['description'] = await hotel.locator('div[class="fff1944c52"]').last.text_content()
                    print(hotel_infos['description'])
                    # url de la page de l'hotel sans les query string
                    hotel_url = await hotel.locator('a[data-testid="title-link"]').get_attribute('href')
                    hotel_infos['url'] = hotel_url.split("?")[0]
                    # score
                    hotel_infos['score'] = await hotel.locator('div[class="f63b14ab7a dff2e52086"]').text_content()
                    # votes en gardant que les chiffres
                    votes_str = await hotel.locator('div[class="fff1944c52 fb14de7f14 eaa8455879"]').text_content()
                    hotel_infos['votes'] = int(''.join([char for char in votes_str if char.isdigit()]))

                    hotels_infos.append(hotel_infos)
                except Exception as e:
                    print(f"Erreur lors de la récupération des données de l'hôtel: {e}")
                    continue
  
            all_hotels_infos.extend(hotels_infos)

            time.sleep(2)

            # Geo data
            # Variable pour stocker la réponse valide
            map_response = None
            async def capture_valid_response(response):
                nonlocal map_response
                if "graphql" in response.url:
                    try:
                        json_data = await response.json()
                        if 'data' in json_data:
                            if 'searchQueries' in json_data['data']:

                                map_response = json_data['data']['searchQueries']
                                print(json_data['data']['searchQueries'].keys())
                                

                            """  if 'searchQueries' in json_data['data'].keys():
                                map_response = response
                                print(json_data['data']['searchQueries'].keys())"""
                    except:
                        pass

            # Écouter les réponses
            page.on("response", capture_valid_response)
            # Clic sur la carte
            await page.locator('button[data-map-trigger-button="1"]').click(force=True)
            # Attendre la réponse valide
            timeout = 0
            while map_response is None and timeout < 50:  # 0 secondes max
                await page.wait_for_timeout(400)
                timeout += 1


            if map_response:

                print("Réponse GraphQL valide récupérée")
                hotels_location_data = []
                try:
                    hotels_raw = map_response['search']['results']

                    for hotel_data in hotels_raw:
                        name = safe_get(hotel_data, 'displayName', 'text')
                        latitude  = safe_get(hotel_data, 'basicPropertyData', 'location', 'latitude')
                        longitude = safe_get(hotel_data, 'basicPropertyData', 'location', 'longitude')
                        slug = safe_get(hotel_data, 'basicPropertyData', 'pageName')

                        if name and slug is not None and latitude is not None and longitude is not None:
                            hotels_location_data.append(
                                {
                                    'city_id': city_id, 
                                    'city': city, 
                                    'name': name, 
                                    'latitude': latitude, 
                                    'longitude': longitude, 
                                    'slug': slug
                                }
                            )
                    
                    all_hotels_locations.extend(hotels_location_data)

                except Exception as e:
                    print("Erreur des données de geolocalisation:", e)

            else:
                print(f"Aucune réponse valide trouvée pour la geolocalistaion des hotels de la ville: {city}")
                continue


            print("Status Code:")
            print(response.status)


        # Sauvegarde locale fichier unique
        with open(LOCAL_DIR + HOTEL_INFOS_FILENAME, 'w', encoding='utf-8') as f:
            json.dump(all_hotels_infos, f, ensure_ascii=False, indent=2)

        with open(LOCAL_DIR + HOTEL_LOCATIONS_FILENAME, 'w', encoding='utf-8') as f:
            json.dump(all_hotels_locations, f, ensure_ascii=False, indent=2)

        # Sauvegarde S3
        try:
            s3_client.put_object(
                Bucket=AWS_BUCKET,
                Key=f"{AWS_BUCKET_DIR}hotels/{HOTEL_INFOS_FILENAME}",
                Body=json.dumps(all_hotels_infos, ensure_ascii=False, indent=2),
                ContentType='application/json'
            )
            s3_client.put_object(
                Bucket=AWS_BUCKET,
                Key=f"{AWS_BUCKET_DIR}hotels/{HOTEL_LOCATIONS_FILENAME}",
                Body=json.dumps(all_hotels_locations, ensure_ascii=False, indent=2),
                ContentType='application/json'
            )
            print(f"Fichiers {HOTEL_INFOS_FILENAME} et {HOTEL_LOCATIONS_FILENAME} sauvegardés dans S3")
        except Exception as e:
            print(f"Erreur sauvegarde S3: {e}")
        
        await browser.close()


def safe_get(data: dict, *keys, default=None):
    """
    Récupère une valeur nested d'un dictionnaire de manière sécurisée.
    Exemple: safe_get(data, 'a', 'b', 'c') équivaut à data.get('a', {}).get('b', {}).get('c', default)
    """
    for key in keys:
        if not isinstance(data, dict):
            return default
        data = data.get(key, default)
        if data is None:
            return default
    return data
        

try:
    asyncio.run(scraper_booking(top_cities))
except Exception as e:
    print(f"Une erreur est survenue: {e}")