-- Foundation for the production campaign store. Apply only in a configured Supabase project.
create table public.campaigns (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  name text not null check (char_length(trim(name)) between 1 and 80),
  goal text not null check (char_length(trim(goal)) between 1 and 1500),
  channel text not null check (channel in ('youtube', 'instagram', 'tiktok')),
  duration_days integer not null check (duration_days between 1 and 90),
  cadence_days integer not null check (cadence_days between 1 and duration_days),
  budget_cents integer not null check (budget_cents between 0 and 100000),
  state text not null default 'draft' check (state in ('draft', 'active', 'paused', 'stopped')),
  created_at timestamptz not null default now()
);

create index campaigns_owner_created on public.campaigns (owner_id, created_at desc);
alter table public.campaigns enable row level security;
revoke all on public.campaigns from anon, authenticated;
grant select on public.campaigns to authenticated;
grant insert (name, goal, channel, duration_days, cadence_days, budget_cents)
  on public.campaigns to authenticated;
grant update (state) on public.campaigns to authenticated;

create policy own_campaigns_read on public.campaigns
  for select to authenticated using ((select auth.uid()) = owner_id);

create policy own_campaigns_insert on public.campaigns
  for insert to authenticated with check ((select auth.uid()) = owner_id and state = 'draft');

create policy own_campaigns_transition on public.campaigns
  for update to authenticated using ((select auth.uid()) = owner_id)
  with check ((select auth.uid()) = owner_id);

create function public.enforce_campaign_transition()
returns trigger language plpgsql set search_path = ''
as $$
begin
  if old.state = new.state
    or (old.state = 'draft' and new.state in ('active', 'stopped'))
    or (old.state = 'active' and new.state in ('paused', 'stopped'))
    or (old.state = 'paused' and new.state in ('active', 'stopped'))
  then
    return new;
  end if;
  raise exception 'Invalid campaign transition' using errcode = '23514';
end;
$$;

create trigger enforce_campaign_transition before update of state on public.campaigns
  for each row execute function public.enforce_campaign_transition();
