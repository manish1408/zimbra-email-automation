CREATE TABLE IF NOT EXISTS classification_config (
    id INT PRIMARY KEY CHECK (id = 1),
    spam_folder TEXT NOT NULL DEFAULT 'Junk',
    default_forward TEXT,
    ack_template TEXT NOT NULL DEFAULT '',
    classification_instructions TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS classification_categories (
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

CREATE TABLE IF NOT EXISTS classification_employees (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb
);

INSERT INTO classification_config (id, spam_folder, default_forward, ack_template, classification_instructions)
VALUES (
    1,
    'Junk',
    'info@gkhair.com',
    E'Thank you for contacting us.\n\nWe have received your email and our team is reviewing it. We will get back to you as soon as possible.\n\nBest regards,\nCustomer Support',
    E'Mark is_spam=true and category=spam for phishing, fake invoices, payment scams, promotional logistics/shipping offers disguised as real shipments, unsolicited billing/finance pitches, and bulk newsletters.\n\nSet needs_live_agent=true when a human must respond (complex support, complaints).\n\nFor person_request emails, extract requested_person (the name the sender asked to reach).'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO classification_categories (
    slug, display_name, classification_hints, folder, forward_to,
    send_ack, needs_live_agent, is_spam, route_by_person, skip_forward, sort_order
) VALUES
    ('spam', 'Spam', 'Phishing, scams, fake invoices, unsolicited bulk marketing blasts.', 'Junk', NULL, FALSE, FALSE, TRUE, FALSE, TRUE, 10),
    ('marketing', 'Marketing', 'Newsletters and promotional content that is not malicious spam.', 'Marketing', NULL, FALSE, FALSE, FALSE, FALSE, TRUE, 20),
    ('logistics', 'Logistics', 'Shipping, freight, warehouse, and supply-chain correspondence.', 'Logistics', 'sc@gkhair.com', TRUE, FALSE, FALSE, FALSE, FALSE, 30),
    ('billing', 'Billing', 'Invoices, payments, and accounting from known vendors or customers.', 'Billing', 'billing@gkhair.com', TRUE, FALSE, FALSE, FALSE, FALSE, 40),
    ('careers', 'Careers', 'Job applications, hiring, and HR-related inquiries.', 'Careers', 'hr@gkhair.com', TRUE, FALSE, FALSE, FALSE, FALSE, 50),
    ('orders', 'Orders', 'Product orders, order status, and fulfilment questions.', 'Orders', 'orders@gkhair.com', TRUE, FALSE, FALSE, FALSE, FALSE, 60),
    ('person_request', 'Person Request', 'Sender asks to reach a specific person by name.', 'Person Requests', NULL, TRUE, FALSE, FALSE, TRUE, FALSE, 70),
    ('customer_support', 'Customer Support', 'Product help, complaints, and support requests needing a human.', 'Customer Support', 'info@gkhair.com', TRUE, TRUE, FALSE, FALSE, FALSE, 80),
    ('enquiry', 'Enquiry', 'General questions and sales enquiries.', 'Enquiries', 'info@gkhair.com', TRUE, TRUE, FALSE, FALSE, FALSE, 90),
    ('general', 'General', 'Everything else that does not fit another category.', 'General', 'info@gkhair.com', TRUE, FALSE, FALSE, FALSE, FALSE, 100)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO classification_employees (name, email, aliases)
SELECT 'meghan', 'meghan@gkhair.com', '["meghan smith", "meghan.smith"]'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM classification_employees WHERE email = 'meghan@gkhair.com');

INSERT INTO classification_employees (name, email, aliases)
SELECT 'meghan smith', 'meghan@gkhair.com', '[]'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM classification_employees WHERE name = 'meghan smith');
