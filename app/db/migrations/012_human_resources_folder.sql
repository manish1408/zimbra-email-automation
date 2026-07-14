-- Move careers / job applications to Human Resources and keep HR on the drafts.
UPDATE classification_categories
SET folder = 'Human Resources',
    forward_to = COALESCE(forward_to, 'hr@gkhair.com'),
    classification_hints = classification_hints || E'

Job applications and hiring enquiries: always move to Human Resources and forward to HR. Draft replies must thank the applicant and say the email is being forwarded to the HR department for further review — do not evaluate qualifications or promise interviews.'
WHERE slug = 'careers';

UPDATE classification_config
SET classification_instructions = classification_instructions || E'

For careers / job applications: set category=careers, needs_forwarding=true, and needs_response_generation=true. Route to Human Resources / HR; do not treat as customer_support.'
WHERE id = 1;
