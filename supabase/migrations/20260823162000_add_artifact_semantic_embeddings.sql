create extension if not exists vector with schema extensions;

alter table public.artifacts
  add column if not exists embedding extensions.vector(384),
  add column if not exists embedding_text text,
  add column if not exists embedding_updated_at timestamptz;

create index if not exists artifacts_embedding_hnsw
  on public.artifacts using hnsw (embedding vector_cosine_ops)
  where embedding is not null;

create or replace function public.match_artifacts(
  query_embedding extensions.vector(384),
  match_canvas_id text,
  match_count integer default 8
)
returns table (artifact_id text, semantic_score double precision)
language sql
stable
set search_path = ''
as $$
  select a.id::text, 1 - (a.embedding OPERATOR(extensions.<=>) query_embedding)
  from public.artifacts a
  where a.canvas_id = match_canvas_id
    and a.embedding is not null
    and a.kind <> 'welcome'
  order by a.embedding OPERATOR(extensions.<=>) query_embedding
  limit greatest(match_count, 1);
$$;
