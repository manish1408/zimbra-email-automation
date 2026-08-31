-- Strengthen sales / promotion / marketing → spam classification (idempotent).
UPDATE classification_config
SET classification_instructions = classification_instructions || E'

Sales/promotion/marketing policy: analyze sender, subject, and body. Mark is_spam=true and category=spam (high confidence) for emails that sell products/services, promote offerings, cold-pitch partnerships that are really sales, or look like marketing/newsletters/promo blasts. Do not use marketing for these — use spam/Junk. Exclude real GK Hair customer questions, transactional mail, and non-sales correspondence.'
WHERE id = 1
  AND classification_instructions NOT LIKE '%Sales/promotion/marketing policy:%';

UPDATE classification_categories
SET classification_hints = classification_hints || E'

Prefer spam for promotional / sales / marketing content. This category should rarely be used; selling and marketing mail goes to spam/Junk.'
WHERE slug = 'marketing'
  AND classification_hints NOT LIKE '%Prefer spam for promotional / sales / marketing content.%';

UPDATE classification_categories
SET classification_hints = classification_hints || E'

Also: unsolicited sales pitches, product/service promotion, cold outreach, and marketing/newsletter blasts — mark is_spam=true with high confidence.'
WHERE slug = 'spam'
  AND classification_hints NOT LIKE '%unsolicited sales pitches, product/service promotion%';
