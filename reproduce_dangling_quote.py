import re


def test_bug():
    # My thought: \b matches at the transition between non-word and word.
    # In 'FROM "public"', the characters are F, R, O, M, space, ", p, u, b, l, i, c, "
    # Transitions:
    # space(non-word) to "(non-word) -> NO \b
    # "(non-word) to p(word) -> YES \b
    # c(word) to "(non-word) -> YES \b

    # So \bpublic\b matches exactly public.
    # If the input is "public"."table", the regex matches:
    # 1. (?:"public"|\bpublic\b) -> matches "public" (first branch) OR public (second branch)
    # 2. .
    # 3. "table"

    # If it matches "public" via the FIRST branch, then group(0) is "public"."table".
    # BUT, regex engines try to match greedily or in order.
    # Let's test if the second branch \bpublic\b matches part of "public"

    sql = 'SELECT * FROM "public"."workflow"'
    pattern_v110 = r'(?i)(?:"public"|\bpublic\b)\s*\.\s*(?:"(\w+)"|(\w+))'

    match = re.search(pattern_v110, sql)
    print(f"Match: {match.group(0)}")
    print(f"Start: {match.start()}")

    # Wait, if Match Start is 14, then it matched "public" correctly.
    # SELECT * FROM  (14 chars)
    # 01234567890123

    # Let's check with a DIFFERENT string
    sql2 = 'SELECT "public"."user"."id" FROM "public"."user"'
    match2 = re.search(pattern_v110, sql2)
    print(f"Match2: {match2.group(0)}")

    # Ah! I think I see it. If I use \bpublic\b it might match the INNER part.
    # But wait, my output above says Match found: '"public"."workflow"'
    # So it IS matching the quotes.


if __name__ == "__main__":
    test_bug()
