
try:
    import iris
    print(f"iris module found at: {iris.__file__}")
    print(f"Attributes: {[a for a in dir(iris) if not a.startswith('_')]}")
    print(f"Has connect: {hasattr(iris, 'connect')}")
except Exception as e:
    print(f"Error importing iris: {e}")

try:
    import iris.dbapi as dbapi
    print("iris.dbapi found")
    print(f"Has connect: {hasattr(dbapi, 'connect')}")
except Exception as e:
    print(f"Error importing iris.dbapi: {e}")

try:
    import irispython
    print(f"irispython found at: {irispython.__file__}")
    print(f"Has connect: {hasattr(irispython, 'connect')}")
except Exception as e:
    print(f"Error importing irispython: {e}")
