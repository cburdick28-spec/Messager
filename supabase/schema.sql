-- Run this in Supabase SQL Editor
create extension if not exists pgcrypto;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text unique not null,
  created_at timestamptz not null default now()
);

create table if not exists public.contacts (
  owner_id uuid not null references public.profiles(id) on delete cascade,
  contact_id uuid not null references public.profiles(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (owner_id, contact_id),
  constraint contacts_not_self check (owner_id <> contact_id)
);

create table if not exists public.chat_groups (
  id uuid primary key default gen_random_uuid(),
  name text unique not null,
  created_by uuid not null references public.profiles(id) on delete cascade,
  created_at timestamptz not null default now()
);

create table if not exists public.group_members (
  group_id uuid not null references public.chat_groups(id) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  joined_at timestamptz not null default now(),
  primary key (group_id, user_id)
);

create table if not exists public.messages (
  id bigint generated always as identity primary key,
  kind text not null check (kind in ('dm','group')),
  dm_a uuid references public.profiles(id) on delete cascade,
  dm_b uuid references public.profiles(id) on delete cascade,
  group_id uuid references public.chat_groups(id) on delete cascade,
  sender_id uuid not null references public.profiles(id) on delete cascade,
  text text not null,
  created_at timestamptz not null default now(),
  constraint dm_shape check (
    (kind = 'dm' and dm_a is not null and dm_b is not null and group_id is null)
    or
    (kind = 'group' and group_id is not null and dm_a is null and dm_b is null)
  )
);

alter table public.profiles enable row level security;
alter table public.contacts enable row level security;
alter table public.chat_groups enable row level security;
alter table public.group_members enable row level security;
alter table public.messages enable row level security;

drop policy if exists profiles_select_all on public.profiles;
create policy profiles_select_all on public.profiles
  for select to authenticated using (true);

drop policy if exists profiles_insert_self on public.profiles;
create policy profiles_insert_self on public.profiles
  for insert to authenticated with check (id = auth.uid());

drop policy if exists profiles_update_self on public.profiles;
create policy profiles_update_self on public.profiles
  for update to authenticated using (id = auth.uid()) with check (id = auth.uid());

drop policy if exists contacts_select_owner on public.contacts;
create policy contacts_select_owner on public.contacts
  for select to authenticated using (owner_id = auth.uid());

drop policy if exists contacts_insert_owner on public.contacts;
create policy contacts_insert_owner on public.contacts
  for insert to authenticated with check (owner_id = auth.uid());

drop policy if exists chat_groups_select_all on public.chat_groups;
create policy chat_groups_select_all on public.chat_groups
  for select to authenticated using (true);

drop policy if exists chat_groups_insert_creator on public.chat_groups;
create policy chat_groups_insert_creator on public.chat_groups
  for insert to authenticated with check (created_by = auth.uid());

drop policy if exists group_members_select_member on public.group_members;
create policy group_members_select_member on public.group_members
  for select to authenticated using (
    user_id = auth.uid()
    or exists (
      select 1 from public.group_members gm2
      where gm2.group_id = group_members.group_id and gm2.user_id = auth.uid()
    )
  );

drop policy if exists group_members_insert_self on public.group_members;
create policy group_members_insert_self on public.group_members
  for insert to authenticated with check (user_id = auth.uid());

drop policy if exists messages_select_visible on public.messages;
create policy messages_select_visible on public.messages
  for select to authenticated using (
    (kind = 'dm' and auth.uid() in (dm_a, dm_b))
    or
    (kind = 'group' and exists (
      select 1 from public.group_members gm
      where gm.group_id = messages.group_id and gm.user_id = auth.uid()
    ))
  );

drop policy if exists messages_insert_dm on public.messages;
create policy messages_insert_dm on public.messages
  for insert to authenticated with check (
    kind = 'dm'
    and sender_id = auth.uid()
    and auth.uid() in (dm_a, dm_b)
  );

drop policy if exists messages_insert_group on public.messages;
create policy messages_insert_group on public.messages
  for insert to authenticated with check (
    kind = 'group'
    and sender_id = auth.uid()
    and exists (
      select 1 from public.group_members gm
      where gm.group_id = messages.group_id and gm.user_id = auth.uid()
    )
  );
