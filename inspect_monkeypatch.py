import sys

try:
    import iris

    print(f"iris module: {iris}")
    print(f"iris dir: {dir(iris)}")
except ImportError:
    print("iris not imported yet")

# Import things that might monkeypatch
try:
    import sqlalchemy_iris

    print("sqlalchemy_iris imported")
    if "iris" in sys.modules:
        print(f"iris dir after sqlalchemy_iris: {dir(sys.modules['iris'])}")
except ImportError:
    print("sqlalchemy_iris not found")

try:
    from iris_devtester import IRISContainer

    print("iris_devtester imported")
    if "iris" in sys.modules:
        print(f"iris dir after iris_devtester: {dir(sys.modules['iris'])}")
except ImportError:
    print("iris_devtester not found")

try:
    import intersystems_iris

    print("intersystems_iris imported")
    if "iris" in sys.modules:
        print(f"iris dir after intersystems_iris: {dir(sys.modules['iris'])}")
except ImportError:
    print("intersystems_iris not found")
