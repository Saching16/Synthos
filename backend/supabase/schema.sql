-- Run against Supabase Postgres (Session mode URI recommended for serverless;
-- use direct connection or pooler URL that matches your asyncpg setup).
-- psql "$SUPABASE_DB_URL" -f backend/supabase/schema.sql

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    filename text NOT NULL,
    sha256 text NOT NULL,
    pages int NOT NULL,
    char_count int NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_sha256 ON documents (sha256);

CREATE TABLE IF NOT EXISTS handbooks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    topic text NOT NULL,
    words int NOT NULL,
    path text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
