import iris


def list_sqluser_tables():
    print("Listing classes in SQLUser package:")
    # Query %Dictionary.ClassDefinition for classes in SQLUser package
    result = iris.sql.exec(
        "SELECT Name FROM %Dictionary.ClassDefinition WHERE Name %STARTSWITH 'SQLUser.'"
    )
    for row in result:
        print(f"Class: {row[0]}")

    print("\nListing tables in SQLUser schema:")
    result = iris.sql.exec(
        "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = 'SQLUser'"
    )
    for row in result:
        print(f"Table: {row[0]}")


if __name__ == "__main__":
    try:
        list_sqluser_tables()
    except Exception as e:
        print(f"Error: {e}")
