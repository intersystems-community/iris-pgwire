/// PostgreSQL catalog support functions for iris-pgwire.
///
/// Exposes the deterministic OID computation to SQL so it can be used inside
/// pg_catalog view definitions. $SYSTEM.Encryption.SHA1Hash cannot be called
/// inline in SQL (SQLCODE -12: ObjectScript system functions are not SQL
/// callable), so it is wrapped in a SqlProc.
///
/// The identity string convention matches iris_pgwire.catalog.oid_generator so
/// both implementations return the same OID for the same object while the
/// view-based and handler-based paths coexist during migration:
///     "<namespace>:<object_type>:<object_name>", already lowercased by the
/// caller (OIDGenerator.get_oid lowercases before hashing, and hashes the
/// lowercased string — so callers here must pass it lowercased too).
Class PGWire.Catalog Extends %RegisteredObject
{

/// PostgreSQL reserves OIDs below this for system objects.
Parameter USEROIDSTART = 16384;

/// Deterministic OID for a catalog object identity string.
///
/// Stable across restarts (pure function of the input), distinct between
/// different inputs, and always >= USEROIDSTART.
///
/// Must stay byte-for-byte equivalent to OIDGenerator._generate_oid in
/// iris_pgwire/catalog/oid_generator.py: SHA-256 of the identity string, first
/// four bytes big-endian, then lifted into the user range by ADDING the start
/// offset when below it (not by modulus — that would produce different OIDs
/// for the same object depending on which path served the query).
ClassMethod PgOid(identity As %String) As %Integer [ SqlName = PG_OID, SqlProc ]
{
    if identity = "" { quit ..#USEROIDSTART }
    set hash = $SYSTEM.Encryption.SHAHash(256, identity)
    set n = 0
    for i = 1:1:4 { set n = (n * 256) + $ascii($extract(hash, i)) }
    if n < ..#USEROIDSTART { set n = n + ..#USEROIDSTART }
    quit n
}

/// The PostgreSQL-facing name of the default schema.
///
/// Returned by a function rather than written as a literal in view DDL: the
/// SQL translation layer rewrites the literal 'public' to the IRIS schema name
/// on its way in, so a view defined with the literal ends up reporting
/// 'SQLUser' to clients — which is precisely the value it exists to hide.
ClassMethod PgPublicSchema() As %String [ SqlName = PG_PUBLIC_SCHEMA, SqlProc ]
{
    quit "pub" _ "lic"
}

/// Convenience wrapper matching OIDGenerator.get_oid(object_type, object_name, namespace).
ClassMethod PgOidFor(objectType As %String, objectName As %String, namespace As %String) As %Integer [ SqlName = PG_OID_FOR, SqlProc ]
{
    quit ..PgOid(namespace _ ":" _ objectType _ ":" _ objectName)
}

}
