from iris_pgwire.schema_mapper import translate_input_schema
import re


def reproduce():
    test_cases = [
        ('SELECT * FROM "public"."workflow"', 'SELECT * FROM SQLUser."workflow"'),
        ("SELECT * FROM public.workflow", 'SELECT * FROM SQLUser."WORKFLOW"'),
        ('SELECT * FROM "public".workflow', 'SELECT * FROM SQLUser."WORKFLOW"'),
        ('SELECT * FROM public."workflow"', 'SELECT * FROM SQLUser."workflow"'),
        ('SELECT * FROM "public"."user"', 'SELECT * FROM SQLUser."user"'),
        ("SELECT * FROM public.user", 'SELECT * FROM SQLUser."USER"'),
    ]

    for sql, expected in test_cases:
        translated = translate_input_schema(sql)
        print(f"Input: {sql}")
        print(f"Output: {translated}")
        assert translated == expected


if __name__ == "__main__":
    reproduce()
