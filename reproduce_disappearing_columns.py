from iris_pgwire.sql_translator.identifier_normalizer import IdentifierNormalizer
import re


def debug_normalize():
    nm = IdentifierNormalizer()
    sql = """CREATE TABLE "features" (
            "id" serial PRIMARY KEY,
            "name" varchar(100) NOT NULL,
            "enabled" boolean DEFAULT false,
            "beta" boolean DEFAULT true,
            "description" text DEFAULT 'This is a feature',
            "created_at" timestamp DEFAULT now()
        )"""

    normalized, _ = nm.normalize(sql)
    print(f"Original:\n{sql}")
    print("-" * 20)
    print(f"Normalized:\n{normalized}")


if __name__ == "__main__":
    debug_normalize()
