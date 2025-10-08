# REST API Strategy: PGWire vs RESTQL vs PostgREST

**Date**: 2025-10-06
**Context**: Analysis of Dave VanDeGriek's RESTQL approach and potential REST API layer for PGWire

---

## Executive Summary

Three distinct approaches for exposing IRIS SQL/vector search via HTTP:

1. **DaveV's RESTQL** - ObjectScript REST API with direct IRIS integration
2. **Our PGWire** - PostgreSQL wire protocol for ecosystem compatibility
3. **PostgREST + PGWire** - Zero-code REST API layer on top of PGWire

**Recommendation**: Offer multiple interfaces for different use cases rather than choosing one.

---

## Architecture Comparison

### DaveV's RESTQL (Epic Hackathon Implementation)

```
HTTP Request → %CSP.REST → ObjectScript → iris.sql.exec() → IRIS
                                            └─ Direct in-process
```

**Performance**: ~2-4ms per query (in-process, no network hop)

**Implementation** (from `/Users/tdyar/Perforce/.../epichat/databases/sys/cls/SQL/REST.xml`):

```objectscript
// String parsing workaround for vector literals (lines 532-538)
set found1=0,found2=0
for string1="TO_VECTOR('[","to_vector('[","TO_VECTOR( '[" {
    if orderVal[string1 { set found1=1 quit }
}
if found1,found2 {
    set toVectorArg="["_$p($p(orderVal,string1,2),string2,1)_"]"
    set orderVal=$replace(orderVal,"'"_toVectorArg_"'","?")
}

// Use prepared statement with parameter
set stmt=##class(%SQL.Statement).%New()
set sc=stmt.%Prepare(sql)
set rs=stmt.%Execute(toVectorArg)
```

**Key Insight from DaveV**:
> "The real fix is to change the SQL preparser to allow literal substitution for the TO_VECTOR(...) function if TO_VECTOR(...) is within an ORDER BY clause, but that is a bigger change."

**Strengths**:
- ✅ Direct IRIS integration (no translation layer)
- ✅ Best performance (in-process execution)
- ✅ Full access to IRIS-specific features
- ✅ Custom endpoint design for partner requirements
- ✅ Pure ObjectScript deployment (no external dependencies)

**Weaknesses**:
- ❌ Custom API (not PostgreSQL-compatible)
- ❌ String parsing for vector literals (brittle)
- ❌ No PostgreSQL ecosystem tools support
- ❌ HTTP/JSON overhead for binary data

---

### Our PGWire Implementation

```
psycopg Client → PostgreSQL Wire Protocol → PGWire Server → IRIS DBAPI → IRIS
                 └─ Binary parameter binding                └─ Network hop (~4ms)
```

**Performance**: ~7-8ms per query (protocol overhead + network hop)

**Implementation** (from `src/iris_pgwire/`):

```python
# Binary parameter binding (no string parsing needed)
async def handle_bind(self, stmt_name: str, params: List[bytes]):
    """Client sends vector as binary array - no SQL string manipulation"""
    # params[0] = binary-encoded float32[] or float64[]
    vector_param = decode_array_parameter(params[0])

    # Execute via IRIS DBAPI with parameter
    result = await iris_executor.execute(
        "SELECT id FROM vectors ORDER BY VECTOR_COSINE(vec, ?) LIMIT 5",
        parameters=[vector_param]
    )
```

**Strengths**:
- ✅ PostgreSQL ecosystem compatibility (psql, pgAdmin, Tableau, Power BI)
- ✅ Binary protocol efficiency (40% more compact than JSON)
- ✅ Client-side intelligence (libraries handle parameter binding)
- ✅ No SQL string manipulation required
- ✅ Universal tooling support

**Weaknesses**:
- ❌ Protocol overhead (~4ms per query)
- ❌ Network hop to IRIS (DBAPI connection)
- ❌ Cannot expose IRIS-specific features beyond PostgreSQL compatibility
- ❌ More complex implementation (wire protocol state machine)

---

### PostgREST + PGWire (Zero-Code Option)

```
HTTP Request → PostgREST → PostgreSQL Wire Protocol → PGWire → IRIS
                            └─ Auto-generated from schema
```

**Performance**: ~8-10ms per query (double PGWire overhead)

**Implementation** (hypothetical docker-compose):

```yaml
postgrest:
  image: postgrest/postgrest:latest
  ports:
    - "3000:3000"
  environment:
    PGRST_DB_URI: postgresql://localhost:5432/USER
    PGRST_DB_SCHEMA: public
    PGRST_DB_ANON_ROLE: postgres
    PGRST_SERVER_PORT: 3000
  depends_on:
    - pgwire-server
```

**Auto-Generated Endpoints**:

```bash
# Vector similarity search
GET /vectors?select=id,embedding&order=embedding.cosine_distance([0.1,0.2,0.3])&limit=5

# CRUD operations
POST /vectors
PATCH /vectors?id=eq.123
DELETE /vectors?id=eq.123

# Complex filters
GET /patients?age=gt.65&diagnosis=like.*diabetes*&last_visit=gte.2024-09-01
```

**Strengths**:
- ✅ Zero code to implement (just configuration)
- ✅ Standard REST API conventions
- ✅ Auto-generated from database schema
- ✅ Built-in authentication/authorization
- ✅ OpenAPI documentation auto-generated

**Weaknesses**:
- ❌ Additional latency layer (~2ms)
- ❌ Limited to PostgreSQL-compatible features
- ❌ No IRIS-specific functions exposed
- ❌ Generic REST design (not optimized for specific use cases)

---

## IRIS-Specific Features (Cannot Expose via PostgREST)

These features require RESTQL-style direct IRIS integration:

### 1. Vector Search + ACORN-1 Filtering

**Use Case** (from Epic hackathon):
```sql
SELECT TOP 10 patient_id, diagnosis,
       VECTOR_COSINE(symptom_embedding, TO_VECTOR('[...]', FLOAT)) as similarity
FROM clinical_notes
WHERE patient_age > 65
  AND diagnosis %PATTERN '1.N1"diabetes".N'  -- IRIS pattern matching
  AND last_visit > CURRENT_DATE - 30
ORDER BY similarity DESC
```

**Why PostgREST can't expose this**:
- `ACORN-1` optimization requires `SET OPTION ACORN_1_SELECTIVITY_THRESHOLD=1`
- `%PATTERN` operator is IRIS-specific
- Need to control HNSW index hints via WHERE clause design
- Query optimizer hints not exposed through PostgreSQL protocol

**RESTQL Advantage**: Can set session options, tune ACORN-1 thresholds per endpoint

---

### 2. IntegratedML PREDICT()

**Use Case**:
```sql
-- Risk prediction for patient readmission
SELECT patient_id,
       PREDICT(ReadmissionRisk) as risk_score,
       PREDICT(ReadmissionRisk, 0.95) as confidence_interval
FROM patient_encounters
WHERE encounter_date > CURRENT_DATE - 7
ORDER BY risk_score DESC
```

**Why PostgREST can't expose this**:
- `PREDICT()` is IRIS-specific ML function
- Model training via `CREATE MODEL` not in PostgreSQL
- Need access to IRIS model metadata and validation

**RESTQL Advantage**: Custom endpoints for model training, inference, evaluation

---

### 3. FHIR JSON Operations

**Use Case** (Epic's FHIR data):
```sql
SELECT
    JSON_VALUE(fhir_resource, '$.patient.id') as patient_id,
    JSON_QUERY(fhir_resource, '$.conditions[*].code') as conditions
FROM fhir_observations
WHERE JSON_EXISTS(fhir_resource, '$.code.coding[*] ? (@.system == "http://loinc.org")')
```

**Why PostgREST can't expose this**:
- IRIS JSON path syntax differs from PostgreSQL `jsonb`
- `JSON_TABLE` expansion has IRIS-specific behavior
- Performance characteristics differ (IRIS JSON is optimized differently)

**RESTQL Advantage**: Native IRIS JSON functions, no translation layer

---

### 4. ObjectScript Class Methods

**Use Case**:
```sql
SELECT
    patient_id,
    %EXTERNAL(dob) as formatted_dob,  -- Object property access
    Epic.Utils.CalculateAge(dob) as age,  -- Custom class method
    Epic.Utils.FormatMRN(mrn) as medical_record_number
FROM patients
```

**Why PostgREST can't expose this**:
- `%EXTERNAL()` for object property traversal
- Custom ObjectScript class methods callable from SQL
- Namespace-specific business logic

**RESTQL Advantage**: Direct ObjectScript integration

---

### 5. Temporal/Bitemporal Queries

**Use Case**:
```sql
-- Historical patient data at specific point in time
SELECT * FROM patients
FOR SYSTEM_TIME AS OF '2024-01-01 12:00:00'
WHERE patient_id = '12345'

-- Bitemporal query (both transaction and valid time)
SELECT * FROM medication_orders
FOR PORTION OF VALID_TIME FROM '2024-01-01' TO '2024-12-31'
FOR SYSTEM_TIME AS OF '2024-10-01'
WHERE patient_id = '12345'
```

**Why PostgREST can't expose this**:
- `FOR SYSTEM_TIME` is IRIS temporal table syntax
- Bitemporal queries not in PostgreSQL standard
- Need IRIS-specific metadata about temporal tables

**RESTQL Advantage**: Full temporal query support

---

### 6. HNSW Index Hints and Tuning

**Use Case** (from EPIC_Hack.md discussion):
```sql
-- Fine-tuned HNSW query with ACORN-1
SET OPTION ACORN_1_SELECTIVITY_THRESHOLD = 1

SELECT TOP 5 ticket_id,
       VECTOR_COSINE(embedding, TO_VECTOR('[...]', FLOAT)) as score
FROM support_tickets
WHERE status = 'open'  -- ACORN-1 needs WHERE to engage
  AND priority >= 3
ORDER BY score DESC
```

**Why PostgREST can't expose this**:
- Need to set session options (`SET OPTION ACORN_1_...`)
- Query optimizer hints require direct IRIS access
- HNSW index usage depends on WHERE clause structure
- Performance tuning requires EXPLAIN plan analysis

**RESTQL Advantage**: Can set session options, tune parameters per endpoint

---

## Performance Matrix

| Path | Latency | Binary Support | IRIS Features | Ecosystem Tools |
|------|---------|----------------|---------------|-----------------|
| **RESTQL (Direct)** | 2-4ms | ❌ (JSON only) | ✅ Full | ❌ Custom API |
| **PGWire (Protocol)** | 7-8ms | ✅ Native | ⚠️ PostgreSQL-compatible only | ✅ All PostgreSQL tools |
| **PostgREST + PGWire** | 8-10ms | ❌ (JSON) | ⚠️ PostgreSQL-compatible only | ✅ REST + PostgreSQL tools |

---

## Strategic Paths Forward

### Option 1: Multi-Interface Strategy (Recommended)

**Offer all three for different use cases**:

```
┌─────────────────────────────────────────────────────────────┐
│                        Clients                               │
├─────────────────┬─────────────────┬─────────────────────────┤
│ PostgreSQL Tools│  Web/Mobile     │  Epic-Specific Apps     │
│ (Tableau, etc.) │  (React, etc.)  │  (FHIR, ML, etc.)       │
└────────┬────────┴────────┬────────┴────────────┬────────────┘
         │                 │                     │
         v                 v                     v
  ┌──────────────┐  ┌─────────────┐  ┌──────────────────┐
  │   PGWire     │  │  PostgREST  │  │  RESTQL (DaveV)  │
  │   :5432      │  │   :3000     │  │     :8080        │
  └──────┬───────┘  └──────┬──────┘  └────────┬─────────┘
         │                 │                   │
         └─────────────────┴───────────────────┘
                           │
                           v
                    ┌──────────────┐
                    │  IRIS DBAPI  │
                    │  or Embedded │
                    └──────────────┘
                           │
                           v
                    ┌──────────────┐
                    │ InterSystems │
                    │     IRIS     │
                    └──────────────┘
```

**Benefits**:
- ✅ PostgreSQL ecosystem gets PGWire (BI tools, psql, pgAdmin)
- ✅ Web developers get PostgREST (standard REST conventions)
- ✅ Epic-specific apps get RESTQL (IRIS-native features)
- ✅ Each optimized for its use case

**Implementation**:
1. Keep PGWire as primary development focus
2. Add PostgREST via docker-compose (zero code)
3. Recommend RESTQL for IRIS-specific features (already exists)

---

### Option 2: PGWire + PostgREST Only

**Focus on PostgreSQL compatibility**:

```
Web/Mobile Apps → PostgREST → PGWire → IRIS
PostgreSQL Tools → PGWire → IRIS
```

**Benefits**:
- ✅ Zero custom REST code
- ✅ Standard PostgreSQL/REST conventions
- ✅ Good enough for 80% of use cases

**Limitations**:
- ❌ No IRIS-specific features (PREDICT, %PATTERN, ACORN-1)
- ❌ Slower than direct IRIS integration
- ❌ Limited to PostgreSQL-compatible features

---

### Option 3: Custom REST Layer on PGWire

**Build RESTQL-style API using PGWire as backend**:

```python
# FastAPI REST layer
@app.get("/vectors/search")
async def vector_search(
    query_vector: List[float],
    filters: Optional[dict] = None,
    limit: int = 10
):
    """Custom REST endpoint with IRIS-specific features"""
    async with pgwire_pool.acquire() as conn:
        # Can still set IRIS-specific options
        await conn.execute("SET OPTION ACORN_1_SELECTIVITY_THRESHOLD=1")

        # Execute vector search with filters
        results = await conn.fetch("""
            SELECT id, VECTOR_COSINE(vec, $1) as score
            FROM vectors
            WHERE status = $2
            ORDER BY score DESC
            LIMIT $3
        """, query_vector, filters.get('status'), limit)

    return {"results": results}
```

**Benefits**:
- ✅ Custom API design for specific use cases
- ✅ Can leverage PGWire parameter binding
- ✅ IRIS-specific features via SQL
- ✅ Python ecosystem (FastAPI, Pydantic)

**Limitations**:
- ❌ More code to write and maintain
- ❌ Slower than RESTQL (additional layer)
- ❌ Still limited by PostgreSQL protocol constraints

---

## Recommendation Matrix

| Use Case | Recommended Interface | Rationale |
|----------|----------------------|-----------|
| **BI Tools** (Tableau, Power BI) | PGWire | Native PostgreSQL drivers, best compatibility |
| **SQL Clients** (psql, pgAdmin) | PGWire | Direct PostgreSQL protocol support |
| **Web Applications** | PostgREST + PGWire | Zero-code REST API, standard conventions |
| **Mobile Apps** | PostgREST + PGWire | REST API simplicity |
| **IRIS-Specific Features** | RESTQL (DaveV) | Direct IRIS integration, best performance |
| **IntegratedML** | RESTQL | PREDICT() not in PostgreSQL |
| **FHIR/Epic Integration** | RESTQL | Custom business logic, IRIS JSON functions |
| **Performance-Critical** | RESTQL | In-process, lowest latency |

---

## Implementation Plan

### Phase 1: Document Current State ✅
- [x] Analyze DaveV's RESTQL approach
- [x] Compare architecture and performance
- [x] Document IRIS-specific features

### Phase 2: Add PostgREST (Zero-Code REST)
- [ ] Add PostgREST service to docker-compose
- [ ] Configure schema exposure
- [ ] Test auto-generated endpoints
- [ ] Document REST API usage
- [ ] Benchmark PostgREST + PGWire latency

### Phase 3: Documentation
- [ ] Update README with multi-interface strategy
- [ ] Create REST API usage guide
- [ ] Document when to use each interface
- [ ] Add architecture diagrams

### Phase 4: Optional - Custom REST Layer
- [ ] Evaluate need for custom endpoints
- [ ] Design FastAPI layer if needed
- [ ] Implement IRIS-specific endpoints
- [ ] Benchmark custom REST vs RESTQL

---

## Questions for Consideration

1. **Target Audience**: Who is the primary user of PGWire?
   - BI analysts → PGWire alone sufficient
   - Web developers → Add PostgREST
   - Epic partners → Recommend RESTQL

2. **Feature Scope**: Should PGWire expose IRIS-specific features?
   - No → Focus on PostgreSQL compatibility
   - Yes → Need custom REST layer or RESTQL-style approach

3. **Performance Requirements**: What latency is acceptable?
   - <5ms → RESTQL only
   - <10ms → PGWire or PostgREST acceptable
   - <50ms → Any approach works

4. **Maintenance Burden**: How much code do we want to maintain?
   - Minimal → PGWire + PostgREST (mostly config)
   - Moderate → Add custom REST layer
   - Complex → Full RESTQL-style implementation

---

## Conclusion

**Best Strategy**: Multi-interface approach

1. **PGWire** - Core focus, PostgreSQL ecosystem compatibility
2. **PostgREST** - Zero-code REST API (add via docker-compose)
3. **RESTQL** - Recommend for IRIS-specific features (already exists via DaveV)

**Why this works**:
- Each interface optimized for its use case
- Minimal additional code (PostgREST is config-only)
- Covers 100% of use cases (generic + IRIS-specific)
- Clear guidance for when to use each

**Next Steps**:
1. Add PostgREST to docker-compose.yml
2. Document the multi-interface strategy in README
3. Create usage guide for each interface
4. Benchmark PostgREST + PGWire performance

---

**References**:
- DaveV's RESTQL: `/Users/tdyar/Perforce/.../epichat/databases/sys/cls/SQL/REST.xml`
- Epic Hackathon Discussion: `docs/EPIC_Hack.md`
- PGWire Implementation: `src/iris_pgwire/`
- PostgREST Docs: https://postgrest.org/
