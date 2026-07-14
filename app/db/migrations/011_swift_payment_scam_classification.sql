-- Clarify that unsolicited SWIFT/TT payment confirmation emails are spam/scams, not billing.
UPDATE classification_config
SET classification_instructions = classification_instructions || E'

Mark is_spam=true and category=spam for unsolicited SWIFT/TT/wire-transfer payment confirmation scams: unknown senders asking you to "confirm receipt of payment", attached remittance notices, or subjects like "SWIFT Ref No" with large USD amounts. These are NOT legitimate billing — real vendor payments come from known GK Hair suppliers and accounting contacts.

Mark is_spam=true and category=spam for unsolicited B2B cold pitches: toner/ink cartridges, office supplies, shipping rates, freight quotes, insurance, SEO, or "quick quote" sales from unknown senders (especially personal domains like outlook.com/gmail.com with empty or generic subjects like "Re:"). These are NOT marketing newsletters — use spam/Junk. Do not generate a reply draft.'
WHERE id = 1;

UPDATE classification_categories
SET classification_hints = classification_hints || E'

Do NOT classify as billing: unsolicited SWIFT/TT payment remittance emails from unknown domains asking to confirm bank receipt. These are payment scams — use category=spam.'
WHERE slug = 'billing';

UPDATE classification_categories
SET classification_hints = classification_hints || E'

Marketing is only for recognizable brand newsletters / known promotional lists. Unsolicited toner, office-supply, freight, or "send your printer model for a quote" cold emails are spam, not marketing.'
WHERE slug = 'marketing';

UPDATE classification_categories
SET classification_hints = classification_hints || E'

Also includes unsolicited cold B2B sales pitches (toner cartridges, office supplies, freight quotes) and SWIFT/TT payment scams.'
WHERE slug = 'spam';
