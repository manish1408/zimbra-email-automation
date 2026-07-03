-- Improve classification for notification senders (e.g. Shopify contact forms).
UPDATE classification_categories
SET classification_hints = classification_hints || E'

Shopify and similar contact-form notifications (e.g. from mailer@shopify.com): read the full email body for the customer''s message and classify as customer_support or orders — not marketing or spam.'
WHERE slug = 'customer_support';

UPDATE classification_config
SET classification_instructions = classification_instructions || E'

Always classify from the full email body content, not the From address. Automated senders (mailer@shopify.com, noreply@, notifications@) may wrap genuine customer enquiries — read CURRENT EMAIL text before choosing category.'
WHERE id = 1;
