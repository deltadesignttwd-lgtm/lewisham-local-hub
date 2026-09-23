-- One-off set-up for the "Local businesses" ads column.
-- Run this once in Supabase: SQL Editor → New query → paste → Run.
-- (Separate from supabase_setup.sql, which only sets up the visitor counter.)

-- 1. The ads table
create table if not exists public.business_ads (
    id            uuid primary key default gen_random_uuid(),
    created_at    timestamptz not null default now(),
    business_name text not null check (char_length(business_name) between 2 and 80),
    description   text not null check (char_length(description) between 10 and 300),
    area          text not null check (char_length(area) <= 40),
    website       text check (char_length(website) <= 200),
    phone         text check (char_length(phone) <= 30),
    email         text not null check (char_length(email) <= 120),  -- for you only, never shown on the site
    image_url     text check (char_length(image_url) <= 300),
    approved      boolean not null default false,                   -- tick this to publish an ad
    expires_on    date                                               -- optional: ad disappears after this date
);

-- 2. Lock it down. Visitors (the "anon" key the site uses) may only:
--    - add a new, unapproved ad, and only fill in the form fields
--    - read approved, unexpired ads, without the email column
alter table public.business_ads enable row level security;

revoke all on public.business_ads from anon, authenticated;
grant insert (business_name, description, area, website, phone, email, image_url)
    on public.business_ads to anon;
grant select (id, created_at, business_name, description, area, website, phone, image_url)
    on public.business_ads to anon;

drop policy if exists "Anyone can submit an ad for review" on public.business_ads;
create policy "Anyone can submit an ad for review"
    on public.business_ads for insert to anon
    with check (approved = false and expires_on is null);

drop policy if exists "Anyone can read approved ads" on public.business_ads;
create policy "Anyone can read approved ads"
    on public.business_ads for select to anon
    using (approved and (expires_on is null or expires_on >= current_date));

-- 3. Image storage: a public bucket that only accepts images up to 2 MB
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('ad-images', 'ad-images', true, 2097152, array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do update
    set public = true,
        file_size_limit = excluded.file_size_limit,
        allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "Anyone can upload an ad image" on storage.objects;
create policy "Anyone can upload an ad image"
    on storage.objects for insert to anon
    with check (bucket_id = 'ad-images');
