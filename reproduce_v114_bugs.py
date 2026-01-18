import re
from iris_pgwire.schema_mapper import translate_input_schema, configure_schema, IRIS_SCHEMA
from iris_pgwire.sql_translator.identifier_normalizer import IdentifierNormalizer


def reproduce_v114_bugs():
    configure_schema(mapping={"public": "SQLUser"})

    print(f"Target IRIS Schema: {IRIS_SCHEMA}")

    # Bug 2: Lack of Idempotency in schema_mapper.py (Double Prefix)
    print("\n--- Bug 2: Double Prefix with Spaces ---")
    # This happens when SQLUser is already there but followed by space + dot + space
    sql_double = 'SELECT * FROM SQLUser . "workflow"'
    translated = translate_input_schema(sql_double)
    print(f"Input:      {sql_double}")
    print(f"Translated: {translated}")
    if "SQLUser . SQLUser" in translated:
        print("FAIL: Double prefix detected")
    else:
        print("SUCCESS: No double prefix")

    # Bug 1: Regex Fragility in identifier_normalizer.py
    print("\n--- Bug 1: Regex Fragility in Normalizer ---")
    nm = IdentifierNormalizer()

    # Test case: Unquoted schema, quoted table with spaces
    sql_fragile = 'SELECT * FROM SQLUser . "WORKFLOW"'
    normalized, _ = nm.normalize(sql_fragile)
    print(f"Input:      {sql_fragile}")
    print(f"Normalized: {normalized}")

    # Logic flaw check: Does it match as a single unit?
    # If it fails, SQLUser might become SQLUSER or the dot/spaces might be handled poorly
    if "SQLUser" in normalized and "SQLUSER" not in normalized:
        print("SUCCESS: SQLUser casing preserved in qualified name with spaces")
    else:
        print("FAIL: SQLUser casing LOST or normalization failed")

    # Another edge case: quoted schema, quoted table, mixed dots
    sql_mixed = 'SELECT * FROM "SQLUser"."workflow"'
    normalized_mixed, _ = nm.normalize(sql_mixed)
    print(f"Input:      {sql_mixed}")
    print(f"Normalized: {normalized_mixed}")


if __name__ == "__main__":
    reproduce_v114_bugs()
