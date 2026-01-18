from iris_pgwire.schema_mapper import translate_input_schema
import re


def verify_schema_mapper():
    test_cases = [
        ('SELECT * FROM "public"."workflow"', 'SELECT * FROM SQLUser."workflow"'),
        ("SELECT * FROM public.workflow", 'SELECT * FROM SQLUser."WORKFLOW"'),
        ('SELECT * FROM "public".workflow', 'SELECT * FROM SQLUser."WORKFLOW"'),
        ('SELECT * FROM public."workflow"', 'SELECT * FROM SQLUser."workflow"'),
        ("SELECT * FROM public.user", 'SELECT * FROM SQLUser."USER"'),
        ("WHERE table_schema = 'public'", "WHERE table_schema = 'SQLUser'"),
        (
            "INSERT INTO public.table VALUES ('public data')",
            "INSERT INTO SQLUser.\"TABLE\" VALUES ('public data')",
        ),
    ]

    for input_sql, expected in test_cases:
        actual = translate_input_schema(input_sql)
        print(f"Input:    {input_sql}")
        print(f"Actual:   {actual}")
        print(f"Expected: {expected}")
        assert actual == expected
        print("✅ Success")
        print("-" * 20)


if __name__ == "__main__":
    verify_schema_mapper()
