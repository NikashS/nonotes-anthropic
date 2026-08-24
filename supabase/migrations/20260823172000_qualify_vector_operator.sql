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
