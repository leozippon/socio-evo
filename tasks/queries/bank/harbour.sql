-- The harbour's register of ships and of their visits.
CREATE TABLE "ship" (
  "ship_id" INTEGER PRIMARY KEY,
  "name" TEXT,
  "flag" TEXT,
  "tonnage" INTEGER
);
CREATE TABLE "visit" (
  "visit_id" INTEGER PRIMARY KEY,
  "ship_id" INTEGER REFERENCES "ship" ("ship_id"),
  "year" INTEGER,
  "berth" TEXT
);
INSERT INTO "ship" VALUES
  (1, 'Aldebaran', 'Norway', 4200),
  (2, 'Brigid', 'Ireland', 1800),
  (3, 'Corvina', 'Portugal', 3100),
  (4, 'Dagmar', 'Denmark', 2600),
  (5, 'Elsinore', 'Denmark', 5400),
  (6, 'Fulmar', 'Norway', 1500),
  (7, 'Gannet', 'Ireland', 2200),
  (8, 'Heimdal', 'Denmark', 3900),
  (9, 'Isolde', 'Portugal', 2800),
  (10, 'Jutland', 'Denmark', 4700);
INSERT INTO "visit" VALUES
  (1, 1, 1999, 'North Quay'),
  (2, 4, 1999, 'Coal Wharf'),
  (3, 9, 2000, 'North Quay'),
  (4, 1, 2000, 'Coal Wharf'),
  (5, 2, 2000, 'Timber Dock'),
  (6, 5, 1999, 'North Quay'),
  (7, 5, 2000, 'North Quay'),
  (8, 7, 2000, 'Timber Dock'),
  (9, 3, 1998, 'Coal Wharf'),
  (10, 8, 2000, 'North Quay'),
  (11, 6, 1999, 'Timber Dock'),
  (12, 10, 1998, 'Coal Wharf'),
  (13, 9, 1999, 'Timber Dock'),
  (14, 4, 2000, 'Coal Wharf'),
  (15, 2, 1998, 'North Quay'),
  (16, 7, 2000, 'Coal Wharf');
