import re

operand = r"(?:[\w\.]+(?:\([^)]*\))?|'[^']*'|\[[^\]]+\]|\?|%s|\$\d+)"

def test_sql(sql):
    print(f"Testing: {sql}")
    
    # <=> operator
    if "<=>" in sql:
        pattern = rf"({operand})\s*<=>\s*({operand})(?:::\w+)?"
        def replace_cosine_distance(match):
            left, right = match.groups()
            return f"(1 - VECTOR_COSINE({left}, {right}))"
        
        new_sql = re.sub(pattern, replace_cosine_distance, sql)
        print(f"Result:  {new_sql}")
    else:
        print("No <=> found")

test_sql('SELECT * FROM t ORDER BY embedding <=> "[1,2,3]"')
test_sql('SELECT * FROM t ORDER BY "embedding" <=> "[1,2,3]"')
test_sql('SELECT * FROM t ORDER BY embedding <=> [1,2,3]::vector')
test_sql('SELECT * FROM t ORDER BY embedding <=> [1,2,3]::"vector"')
test_sql('SELECT * FROM t ORDER BY embedding <=> [1,2,3]::double precision')
test_sql('SELECT * FROM t ORDER BY col1::vector <=> col2')
