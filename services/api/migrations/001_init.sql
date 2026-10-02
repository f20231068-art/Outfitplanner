-- 001_init.sql: the first version of the schema.
-- Plain SQL on purpose: read it top to bottom to see exactly what the database holds.

-- ---------------------------------------------------------------------------------------------
-- Users. The password is stored only as an Argon2id hash, never the password itself.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email         text        NOT NULL,
    password_hash text        NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    disabled_at   timestamptz,                       -- set to lock an account without deleting it
    CONSTRAINT users_email_shape CHECK (position('@' in email) > 1 AND length(email) <= 254)
);
-- "A@x.com" and "a@x.com" are the same person: uniqueness is checked on the lower-cased email.
CREATE UNIQUE INDEX users_email_lower_idx ON users (lower(email));

-- ---------------------------------------------------------------------------------------------
-- Refresh tokens: the long-lived "stay logged in" credential. Only a hash is stored, so a copy of
-- the database cannot be used to log in. Each use swaps the token for a new one (rotation); seeing
-- an already-used token again means it was stolen, and its whole family is revoked.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE refresh_tokens (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    family_id  uuid        NOT NULL,                 -- every token descended from one login
    token_hash text        NOT NULL UNIQUE,          -- SHA-256 of the random token
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at    timestamptz,                          -- when it was exchanged for a new one
    revoked_at timestamptz
);
CREATE INDEX refresh_tokens_user_idx   ON refresh_tokens (user_id);
CREATE INDEX refresh_tokens_family_idx ON refresh_tokens (family_id);

-- ---------------------------------------------------------------------------------------------
-- Conversations. The LangGraph "thread id" is this row's id, so a conversation can pause for the
-- user's answer and resume later, even after a restart.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE conversations (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    title      text        NOT NULL DEFAULT 'New conversation',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
-- "this user's most recent conversations" is the hot query: one index serves it
CREATE INDEX conversations_user_recent_idx ON conversations (user_id, updated_at DESC);

-- ---------------------------------------------------------------------------------------------
-- Outfits shown to the user, and the two products in each. A batch is one round of 4 outfits.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE outfits (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid        NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
    user_id         uuid        NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    batch           integer     NOT NULL DEFAULT 1,
    position        smallint    NOT NULL CHECK (position >= 1),
    style_name      text        NOT NULL,
    total_inr       integer     NOT NULL CHECK (total_inr > 0),
    confidence      text        NOT NULL CHECK (confidence IN ('high', 'low')),
    rationale       text        NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, batch, position)
);
CREATE INDEX outfits_user_recent_idx ON outfits (user_id, created_at DESC);

CREATE TABLE outfit_items (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    outfit_id    uuid    NOT NULL REFERENCES outfits (id) ON DELETE CASCADE,
    slot         text    NOT NULL CHECK (slot IN ('top', 'bottom')),
    product_id   text,                               -- opaque id from the search tool
    title        text    NOT NULL,
    retailer     text    NOT NULL,
    price_inr    integer NOT NULL CHECK (price_inr >= 0),
    mrp_inr      integer,
    url          text    NOT NULL,
    url_kind     text,
    image_url    text    NOT NULL,
    verification jsonb   NOT NULL,                   -- the requested-vs-found comparison, kept as evidence
    UNIQUE (outfit_id, slot)
);
-- "does this product belong to one of this user's outfits?" is asked before every buy-link lookup
CREATE INDEX outfit_items_product_idx ON outfit_items (product_id);

-- ---------------------------------------------------------------------------------------------
-- The audit log: an append-only record, hash-chained so that tampering is detectable.
-- Each row stores the hash of the row before it; changing or deleting any row breaks every hash
-- after it, and /audit/verify finds the first broken link.
-- ---------------------------------------------------------------------------------------------
CREATE TABLE audit_log (
    id        bigserial PRIMARY KEY,
    ts        timestamptz NOT NULL,
    actor     text        NOT NULL,                  -- a user id, or 'system'
    action    text        NOT NULL,                  -- e.g. 'login', 'tool_call'
    details   jsonb       NOT NULL DEFAULT '{}',     -- ids and counts only: never passwords, tokens or message text
    prev_hash text        NOT NULL,
    hash      text        NOT NULL UNIQUE
);
CREATE INDEX audit_log_actor_ts_idx ON audit_log (actor, ts);

CREATE FUNCTION audit_log_is_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_is_append_only();

CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_is_append_only();
