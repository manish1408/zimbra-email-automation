-- Scope classification categories per mailbox. Global (account='') keeps spam
-- only; non-spam categories become a template copied onto each inbox.

CREATE TABLE IF NOT EXISTS classification_category_templates (
    id SERIAL PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    classification_hints TEXT NOT NULL DEFAULT '',
    folder TEXT NOT NULL,
    forward_to TEXT,
    send_ack BOOLEAN NOT NULL DEFAULT TRUE,
    needs_live_agent BOOLEAN NOT NULL DEFAULT FALSE,
    is_spam BOOLEAN NOT NULL DEFAULT FALSE,
    route_by_person BOOLEAN NOT NULL DEFAULT FALSE,
    skip_forward BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order INT NOT NULL DEFAULT 0,
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS mailbox_classification_config (
    account TEXT PRIMARY KEY,
    extra_instructions TEXT NOT NULL DEFAULT '',
    default_forward TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE classification_categories
    ADD COLUMN IF NOT EXISTS account TEXT NOT NULL DEFAULT '';

ALTER TABLE classification_categories
    DROP CONSTRAINT IF EXISTS classification_categories_slug_key;

CREATE UNIQUE INDEX IF NOT EXISTS classification_categories_account_slug_key
    ON classification_categories (account, slug);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'classification_categories_account_slug_key'
    ) THEN
        ALTER TABLE classification_categories
            ADD CONSTRAINT classification_categories_account_slug_key
            UNIQUE USING INDEX classification_categories_account_slug_key;
    END IF;
EXCEPTION
    WHEN duplicate_object THEN
        NULL;
END $$;

INSERT INTO classification_category_templates (
    slug, display_name, classification_hints, folder, forward_to,
    send_ack, needs_live_agent, is_spam, route_by_person, skip_forward,
    sort_order, enabled
)
SELECT
    slug, display_name, classification_hints, folder, forward_to,
    send_ack, needs_live_agent, is_spam, route_by_person, skip_forward,
    sort_order, enabled
FROM classification_categories
WHERE account = '' AND is_spam = FALSE
ON CONFLICT (slug) DO NOTHING;

INSERT INTO classification_category_templates (
    slug, display_name, classification_hints, folder, forward_to,
    send_ack, needs_live_agent, is_spam, route_by_person, skip_forward,
    sort_order, enabled
) VALUES
    (
        'undelivered',
        'Undelivered',
        'Mailer-daemon bounce and delivery-failure notices.',
        'Undelivered',
        NULL,
        FALSE,
        FALSE,
        FALSE,
        FALSE,
        TRUE,
        15,
        TRUE
    ),
    (
        'platform_notification',
        'Platform Notifications',
        'Automated notifications from Facebook, Shopify Audiences, DIDWW, and similar platforms.',
        'Platform Notifications',
        NULL,
        FALSE,
        FALSE,
        FALSE,
        FALSE,
        TRUE,
        25,
        TRUE
    )
ON CONFLICT (slug) DO NOTHING;

DELETE FROM classification_categories
WHERE account = '' AND is_spam = FALSE;

INSERT INTO mailbox_classification_config (account, extra_instructions, default_forward, updated_at)
SELECT
    ms.account,
    '',
    (SELECT default_forward FROM classification_config WHERE id = 1),
    NOW()
FROM mailbox_state ms
ON CONFLICT (account) DO NOTHING;

INSERT INTO classification_categories (
    account, slug, display_name, classification_hints, folder, forward_to,
    send_ack, needs_live_agent, is_spam, route_by_person, skip_forward,
    sort_order, enabled
)
SELECT
    ms.account,
    t.slug,
    t.display_name,
    t.classification_hints,
    t.folder,
    t.forward_to,
    t.send_ack,
    t.needs_live_agent,
    t.is_spam,
    t.route_by_person,
    t.skip_forward,
    t.sort_order,
    t.enabled
FROM mailbox_state ms
CROSS JOIN classification_category_templates t
WHERE NOT EXISTS (
    SELECT 1
    FROM classification_categories c
    WHERE c.account = ms.account AND c.slug = t.slug
);
