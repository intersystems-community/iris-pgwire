-- IRIS Healthcare Schema Initialization
-- Purpose: Create Patients and LabResults tables for Superset 4 example
-- Target: InterSystems IRIS via PGWire PostgreSQL wire protocol
-- Date: 2025-01-05

-- Clean re-initialization: Drop existing tables
DROP TABLE IF EXISTS LabResults;
DROP TABLE IF EXISTS Patients;

-- Patients Table: Synthetic healthcare demographics
-- 250 patient records with realistic but generated data
CREATE TABLE Patients (
    PatientID INT PRIMARY KEY,
    FirstName VARCHAR(50) NOT NULL,
    LastName VARCHAR(50) NOT NULL,
    DateOfBirth DATE NOT NULL,
    Gender VARCHAR(10) NOT NULL,  -- M, F, Other
    Status VARCHAR(20) NOT NULL,  -- Active, Discharged, Deceased
    AdmissionDate DATE NOT NULL,
    DischargeDate DATE            -- NULL for Active patients
);

-- LabResults Table: Synthetic lab test results
-- 400 lab result records (avg 1.6 per patient)
CREATE TABLE LabResults (
    ResultID INT PRIMARY KEY,
    PatientID INT NOT NULL,
    TestName VARCHAR(100) NOT NULL,
    TestDate DATE NOT NULL,
    Result NUMERIC(10,2) NOT NULL,
    Unit VARCHAR(20) NOT NULL,
    ReferenceRange VARCHAR(50) NOT NULL,
    Status VARCHAR(20) NOT NULL,  -- Normal, Abnormal, Critical
    FOREIGN KEY (PatientID) REFERENCES Patients(PatientID)
);

-- Create indexes for performance
CREATE INDEX idx_patients_status ON Patients(Status);
CREATE INDEX idx_patients_admission ON Patients(AdmissionDate);
CREATE INDEX idx_labresults_patient ON LabResults(PatientID);
CREATE INDEX idx_labresults_testdate ON LabResults(TestDate);
CREATE INDEX idx_labresults_status ON LabResults(Status);
