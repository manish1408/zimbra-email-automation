-- Enable conversation-based draft replies for orders; clarify support/orders behavior.
UPDATE classification_categories
SET classification_hints = 'Product orders, order status, fulfilment, and shipping questions. Generate a reply draft that references order details and prior thread context.'
WHERE slug = 'orders';

UPDATE classification_categories
SET classification_hints = 'Product help, complaints, and support requests. Generate acknowledgement and conversation-based reply drafts for the support team.'
WHERE slug = 'customer_support';

UPDATE classification_config
SET classification_instructions = E'Mark is_spam=true and category=spam for phishing, fake invoices, payment scams, promotional logistics/shipping offers disguised as real shipments, unsolicited billing/finance pitches, and bulk newsletters.\n\nFor customer_support and orders, always produce draft_reply_text grounded in the email thread.\n\nSet needs_live_agent=true when a human must respond (complex support, complaints).\n\nFor person_request emails, extract requested_person (the name the sender asked to reach).'
WHERE id = 1;
