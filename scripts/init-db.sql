-- Schemas da arquitetura Medallion (architecture.md §3).
-- Apenas os SCHEMAS; as TABELAS são criadas por migrations Alembic (architecture.md §4).
CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;
