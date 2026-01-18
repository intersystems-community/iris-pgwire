import re


def test_regex():
    sql = """CREATE TABLE "features" (
            "id" serial PRIMARY KEY,
            "name" varchar(100) NOT NULL,
            "enabled" boolean DEFAULT false,
            "beta" boolean DEFAULT true,
            "description" text DEFAULT 'This is a feature',
            "created_at" timestamp DEFAULT now()
        )"""

    # This is the regex I used
    pattern = r"(?i),?\s*[\w\"]+\s+[\w\"]+(?:\s*\([^)]*\))?\s+GENERATED\s+ALWAYS\s+AS\s*\([^)]+\)\s*STORED"

    match = re.search(pattern, sql)
    if match:
        print(f"Match found: {match.group(0)}")
    else:
        print("No match found")


if __name__ == "__main__":
    test_regex()
