# Roadmap: IRIS PGWire Development

**Last Updated**: 2025-12-27
**Related**: [Known Limitations](https://github.com/intersystems-community/iris-pgwire/blob/main/KNOWN_LIMITATIONS.md), [Contributing](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/developer_guide.md)

---

## ✅ Implemented (Production-Ready)

- **PostgreSQL Wire Protocol v3**: Handshake, simple & extended query protocols
- **Authentication**: SCRAM-SHA-256, OAuth 2.0, IRIS Wallet
- **Vector Operations**: pgvector syntax (`<=>`, `<#>`), HNSW indexes
- **COPY Protocol**: Bulk import/export with CSV format (600+ rows/sec)
- **Transactions**: BEGIN/COMMIT/ROLLBACK with savepoints
- **Async SQLAlchemy**: FastAPI integration, connection pooling
- **Dual Backend Architecture**: DBAPI + Embedded Python execution paths
- **Multi-Language Support**: 8 drivers at 100% (Python, Node.js, Java, .NET, Go, Ruby, Rust, PHP)
- **ORM Schema Mapping**: `public` ↔ configurable IRIS schema for Prisma, SQLAlchemy introspection
- **pg_catalog Emulation**: 6 tables + 5 functions for ORM introspection

**Test Coverage**: Over 100 tests passing across 8 programming languages

---

## 🚧 Known Limitations

**Note**: These limitations are common across PostgreSQL wire protocol implementations. For example, PgBouncer also omits GSSAPI support, and QuestDB does not support SSL/TLS.

### Protocol & Authentication
- **SSL/TLS wire protocol**: Not implemented - use reverse proxy (nginx/HAProxy) for transport encryption
- **Kerberos/GSSAPI**: Not implemented - use OAuth 2.0 or IRIS Wallet instead

### Vector Operations
- **Cosine distance** (`<=>`): ✅ Supported → `VECTOR_COSINE()`
- **Dot product** (`<#>`): ✅ Supported → `VECTOR_DOT_PRODUCT()`
- **L2/Euclidean** (`<->`): ❌ Not available (IRIS database limitation - only cosine and dot product supported)

### PostgreSQL Compatibility
- **System catalogs**: Partial `pg_catalog` support (6 tables + 5 functions) - see [PG_CATALOG.md](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PG_CATALOG.md)
- **CREATE EXTENSION**: Not supported (IRIS has native vector support)

### Tools That Won't Work via PGWire

| Category | Won't Work (via PGWire) | Community Alternative |
|----------|-------------------------|------------------------|
| **LangChain** | `langchain_community.PGVector` | [`langchain-iris`](https://github.com/caretdev/langchain-iris) (community) |
| **LlamaIndex** | `llama_index.PGVectorStore` | [`llama-iris`](https://github.com/caretdev/llama-iris) (community) |
| **Haystack** | `haystack.PGVector` | psycopg3 with custom retriever |
| **ORM/Database** | SQLAlchemy + psycopg2 | psycopg3 directly |
| **Admin Tools** | pgAdmin (full features) | IRIS Management Portal |

---

## 📋 Future Enhancements

### Security
- **SSL/TLS wire protocol encryption**: Direct TLS support (currently requires reverse proxy)
- **Kerberos/GSSAPI authentication**: Enterprise single sign-on

### Performance
- **Connection limits & rate limiting**: Prevent resource exhaustion
- **executemany() bulk operations**: Batch parameter binding for faster inserts
- **Query result streaming**: Reduce memory for large result sets
- **Prepared statement caching**: Reuse parsed/translated statements

### PostgreSQL Compatibility
- **Advanced SQL features**: CTEs (Common Table Expressions), window functions
- **Additional catalog tables**: Expand pg_catalog coverage for more ORMs
- **Additional catalog functions**: More PostgreSQL utility functions

### Tooling
- **Prometheus metrics endpoint**: Built-in observability
- **Health check endpoint**: Kubernetes/Docker readiness probes
- **Admin UI**: Web interface for monitoring connections and queries

---

## Community Alternatives for RAG

For RAG applications and vector workloads, community-maintained packages are available:

```bash
# Install community-supported LangChain/LlamaIndex integrations
pip install langchain-iris llama-iris
```

**LangChain Example** (community package):
```python
from langchain_iris import IRISVector

db = IRISVector(
    embedding_function=embeddings,
    connection_string="iris://_SYSTEM:SYS@localhost:1972/USER",
    collection_name="my_docs"
)
db.add_texts(["Document 1", "Document 2"])
results = db.similarity_search("query", k=5)
```

**PGWire Approach** (direct psycopg3):
```python
import psycopg
with psycopg.connect("host=localhost port=5432 dbname=USER") as conn:
    cur.execute("SELECT * FROM docs ORDER BY embedding <=> %s LIMIT 5", (query_vec,))
```

---

## See Also

- [Known Limitations](https://github.com/intersystems-community/iris-pgwire/blob/main/KNOWN_LIMITATIONS.md) - Full limitation details
- [Contributing Guide](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/developer_guide.md) - How to contribute
- [PG_CATALOG Documentation](https://github.com/intersystems-community/iris-pgwire/blob/main/docs/PG_CATALOG.md) - Catalog emulation details
