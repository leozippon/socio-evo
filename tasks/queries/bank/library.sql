-- A lending library's books and its loans to members.
CREATE TABLE "book" (
  "book_id" INTEGER PRIMARY KEY,
  "title" TEXT,
  "author" TEXT,
  "year" INTEGER
);
CREATE TABLE "loan" (
  "loan_id" INTEGER PRIMARY KEY,
  "book_id" INTEGER REFERENCES "book" ("book_id"),
  "member" TEXT,
  "lent" TEXT
);
INSERT INTO "book" VALUES
  (1, 'The Salt Road', 'M. Okafor', 1987),
  (2, 'Tides of the Estuary', 'L. Brandt', 1972),
  (3, 'A Short History of Rope', 'P. Haldane', 1995),
  (4, 'Winter on the Quays', 'S. Ferreira', 1990),
  (5, 'The Lamplighter', 'J. Novak', 1964),
  (6, 'Charts and Soundings', 'R. Iversen', 1981),
  (7, 'The Mill Girls', 'A. Kowalski', 1999),
  (8, 'Letters from Lisbon', 'S. Ferreira', 1985),
  (9, 'Steam and Iron', 'P. Haldane', 1978),
  (10, 'The Ferryman''s Daughter', 'J. Novak', 1993);
INSERT INTO "loan" VALUES
  (1, 1, 'Ada Price', '2000-03-02'),
  (2, 2, 'Ben Osei', '2000-03-04'),
  (3, 1, 'Ada Price', '2000-04-11'),
  (4, 4, 'Cyril Mather', '2000-04-15'),
  (5, 6, 'Ada Price', '2000-05-01'),
  (6, 7, 'Dora Lind', '2000-05-03'),
  (7, 4, 'Cyril Mather', '2000-06-20'),
  (8, 9, 'Ben Osei', '2000-07-07'),
  (9, 3, 'Ada Price', '2000-07-19'),
  (10, 7, 'Cyril Mather', '2000-08-02'),
  (11, 10, 'Eli Rowe', '2000-09-12'),
  (12, 2, 'Dora Lind', '2000-10-30');
