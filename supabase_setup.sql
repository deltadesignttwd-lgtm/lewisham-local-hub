-- One-off set-up for the visitor counter.
-- Run this once in Supabase: Project → SQL Editor → New query → paste → Run.

create table if not exists public.site_counter (
    name  text primary key,
    count bigint not null default 0
);

insert into public.site_counter (name, count)
values ('visits', 0)
on conflict (name) do nothing;

-- Lock the table: with row level security on and no policies, the public key
-- cannot read or change it directly. Visitors can only add 1 through the function below.
alter table public.site_counter enable row level security;

create or replace function public.increment_visits()
returns bigint
language sql
security definer
set search_path = public
as $$
    update public.site_counter
    set count = count + 1
    where name = 'visits'
    returning count;
$$;

revoke all on function public.increment_visits() from public;
grant execute on function public.increment_visits() to anon;
