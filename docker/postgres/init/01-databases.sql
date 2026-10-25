-- Runs once, on first start of an empty Postgres volume.
-- The app database (POSTGRES_DB) is created by the image; Langfuse gets its own.
CREATE DATABASE langfuse;
