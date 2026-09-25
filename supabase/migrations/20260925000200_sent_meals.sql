-- One row per meal notification sent, keyed by subscriber, meal and the
-- subscriber's local date. Several runs can see the same due meal (the
-- on-time trigger and the catch-up heartbeat), and inserting this row
-- first is how a run claims the send: the primary key makes a second
-- claim a no-op. A run that fails to send deletes its claim so a later
-- run retries. See menu/schedule.py.
--
-- Doubles as a send history. Only the secret key can read it.

create table public.sent_meals (
  subscriber_id uuid not null references public.subscribers (id) on delete cascade,
  meal text not null,
  local_date date not null,
  sent_at timestamptz not null default now(),
  primary key (subscriber_id, meal, local_date)
);

alter table public.sent_meals enable row level security;
