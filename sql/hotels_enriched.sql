#city_id,city,name,description,url,score,votes,latitude,longitude
CREATE TABLE IF NOT EXISTS "hotels_enriched" (
  "id" smallint PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
  "city_id" smallint NOT NULL,
  "city" varchar(100) NOT NULL,
  "name" varchar(255) NOT NULL,
  "description" text,
  "url" text,
  "score" double precision,
  "votes" double precision,
  "latitude" double precision,
  "longitude" double precision
);
