-- IRIS Initial Setup for PostgreSQL Wire Protocol
-- Execute during container startup to prepare IRIS for PGWire compatibility

-- Enable IntegratedML
SET ^%SYS("SQLML") = 1

-- Create sample vector table for testing
CREATE TABLE IF NOT EXISTS VectorDemo (
    id INTEGER,
    name VARCHAR(100),
    embedding VECTOR(1024) DATATYPE DOUBLE,
    metadata LONGVARCHAR
)

-- Create sample ML training data
CREATE TABLE IF NOT EXISTS MLTrainingData (
    id INTEGER,
    feature1 DECIMAL(10,4),
    feature2 DECIMAL(10,4),
    feature3 DECIMAL(10,4),
    target VARCHAR(20)
)

-- Insert sample vector data
INSERT INTO VectorDemo (id, name, embedding, metadata) VALUES
(1, 'Test Vector 1', TO_VECTOR('[1,0,0,0]'), '{"type": "demo", "category": "test"}'),
(2, 'Test Vector 2', TO_VECTOR('[0,1,0,0]'), '{"type": "demo", "category": "validation"}'),
(3, 'Test Vector 3', TO_VECTOR('[0,0,1,0]'), '{"type": "demo", "category": "production"}')

-- Insert sample ML training data
INSERT INTO MLTrainingData (id, feature1, feature2, feature3, target) VALUES
(1, 1.1, 2.2, 3.3, 'class_A'),
(2, 1.5, 2.8, 3.1, 'class_B'),
(3, 2.1, 3.2, 4.3, 'class_A'),
(4, 2.5, 3.8, 4.1, 'class_B'),
(5, 3.1, 4.2, 5.3, 'class_A')

-- Create sample IntegratedML model for testing
CREATE MODEL IF NOT EXISTS DemoMLModel PREDICTING (target) FROM MLTrainingData

-- Train the model
TRAIN MODEL DemoMLModel

WRITE "IRIS PostgreSQL Wire Protocol setup complete!", !
WRITE "- IntegratedML enabled", !
WRITE "- Sample vector table created with test data", !
WRITE "- Sample ML model trained and ready", !
WRITE "- Ready for PostgreSQL wire protocol connections", !