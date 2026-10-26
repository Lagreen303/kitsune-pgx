.mode column
.headers on
SELECT state, COUNT(1) AS n FROM runs GROUP BY state ORDER BY state;
SELECT gse,
  SUM(CASE WHEN state='FAILED' THEN 1 ELSE 0 END) AS failed,
  SUM(CASE WHEN state='DONE' THEN 1 ELSE 0 END) AS done,
  SUM(CASE WHEN state='PENDING' THEN 1 ELSE 0 END) AS pending,
  COUNT(1) AS total
FROM runs
GROUP BY gse
HAVING failed > 0
ORDER BY failed DESC, gse;
