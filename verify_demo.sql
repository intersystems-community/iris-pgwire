DROP TABLE IF EXISTS MyPatients;
CREATE TABLE MyPatients (id INT, category VARCHAR(255));
INSERT INTO MyPatients (id, category) VALUES (1, 'Follow-up');
INSERT INTO MyPatients (id, category) VALUES (2, 'New patient');
INSERT INTO MyPatients (id, category) VALUES (3, 'Follow-up');

DROP TABLE IF EXISTS medical_notes;
CREATE TABLE medical_notes (id INT, content VARCHAR(255), embedding VECTOR(DOUBLE, 3));
-- Use pgvector format (raw bracketed strings)
INSERT INTO medical_notes (id, content, embedding) VALUES (1, 'Patient has a cough', '[0.1, 0.2, 0.3]');
INSERT INTO medical_notes (id, content, embedding) VALUES (2, 'Patient has a fever', '[0.8, 0.1, 0.1]');

-- Try INSERT ... SELECT too (to verify fix for mangling)
INSERT INTO medical_notes (id, content, embedding) SELECT 3, 'Patient has a headache', TO_VECTOR('[0.1, 0.8, 0.1]', DOUBLE);

-- Verify searches
SELECT COUNT(*) FROM MyPatients WHERE category = 'Follow-up';
-- Search query with literal string for optimizer happiness
SELECT id, content FROM medical_notes ORDER BY embedding <=> '[0.1, 0.2, 0.3]' LIMIT 5;
