from iris_pgwire.schema_mapper import translate_input_schema, configure_schema
import re


def reproduce_bugs():
    # Bug 1: Hardcoded "public"
    print("--- Bug 1: Hardcoded 'public' ---")
    configure_schema(mapping={"drizzle": "SQLUser"})
    sql1 = 'SELECT * FROM drizzle."workflow"'
    translated1 = translate_input_schema(sql1)
    print(f"Input: {sql1}")
    print(f"Output: {translated1}")
    # Current v1.1.1 will likely return SELECT * FROM drizzle."workflow"

    # Bug 2: Missing Bare Table Mapping
    print("\n--- Bug 2: Missing Bare Table Mapping ---")
    sql2 = 'SELECT * FROM "workflow"'
    translated2 = translate_input_schema(sql2)
    print(f"Input: {sql2}")
    print(f"Output: {translated2}")
    # Current v1.1.1 will likely return SELECT * FROM "workflow"

    sql3 = "SELECT * FROM workflow"
    translated3 = translate_input_schema(sql3)
    print(f"Input: {sql3}")
    print(f"Output: {translated3}")


if __name__ == "__main__":
    reproduce_bugs()
