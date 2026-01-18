from iris_pgwire.schema_mapper import translate_input_schema, configure_schema, IRIS_SCHEMA
import re


def test_fixes():
    print(f"Target IRIS Schema: {IRIS_SCHEMA}")

    # Setup custom mapping
    configure_schema(mapping={"drizzle": "SQLUser", "public": "SQLUser"})

    test_cases = [
        # Bug 1: Hardcoded "public"
        ('SELECT * FROM drizzle."workflow"', 'SELECT * FROM SQLUser."WORKFLOW"'),
        ("SELECT * FROM drizzle.workflow", 'SELECT * FROM SQLUser."WORKFLOW"'),
        # Bug 2: Missing Bare Table Mapping
        ('SELECT * FROM "workflow"', 'SELECT * FROM SQLUser."WORKFLOW"'),
        ("SELECT * FROM workflow", 'SELECT * FROM SQLUser."WORKFLOW"'),
        ("INSERT INTO workflow (id) VALUES (1)", 'INSERT INTO SQLUser."WORKFLOW" (id) VALUES (1)'),
        ('UPDATE "workflow" SET status = 1', 'UPDATE SQLUser."WORKFLOW" SET status = 1'),
        ("DELETE FROM workflow", 'DELETE FROM SQLUser."WORKFLOW"'),
        ("CREATE TABLE workflow (id int)", 'CREATE TABLE SQLUser."WORKFLOW" (id int)'),
        # Bug 3: Quoted Schema casing/quoting
        ('SELECT * FROM "public"."workflow"', 'SELECT * FROM SQLUser."WORKFLOW"'),
        ('SELECT * FROM public."workflow"', 'SELECT * FROM SQLUser."WORKFLOW"'),
        ('SELECT * FROM "public".workflow', 'SELECT * FROM SQLUser."WORKFLOW"'),
        # Mixed
        (
            'SELECT * FROM public.user JOIN "workflow" ON user.id = workflow.user_id',
            'SELECT * FROM SQLUser."USER" JOIN SQLUser."WORKFLOW" ON user.id = workflow.user_id',
        ),
    ]

    passed = 0
    for i, (input_sql, expected) in enumerate(test_cases):
        actual = translate_input_schema(input_sql)
        if actual == expected:
            print(f"Test {i + 1} PASSED")
            passed += 1
        else:
            print(f"Test {i + 1} FAILED")
            print(f"  Input:    {input_sql}")
            print(f"  Actual:   {actual}")
            print(f"  Expected: {expected}")

    print(f"\nPassed {passed}/{len(test_cases)} tests")


if __name__ == "__main__":
    test_fixes()
