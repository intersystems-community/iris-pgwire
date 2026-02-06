try:
    import intersystems_iris

    print(f"intersystems_iris found at: {intersystems_iris.__file__}")
    print(f"Attributes: {[a for a in dir(intersystems_iris) if not a.startswith('_')]}")
except Exception as e:
    print(f"Error importing intersystems_iris: {e}")

try:
    import intersystems_iris.dbapi._DBAPI as dbapi

    print("intersystems_iris.dbapi._DBAPI found")
    print(f"Has connect: {hasattr(dbapi, 'connect')}")
except Exception as e:
    print(f"Error importing intersystems_iris.dbapi._DBAPI: {e}")
