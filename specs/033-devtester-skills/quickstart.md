# Quickstart: Automated Testing with iris-devtester

This guide shows how to leverage the new automated testing infrastructure in `iris-pgwire`.

## Prerequisites
1. **Docker Desktop** running.
2. **Local iris-devtester**: Clone and install in editable mode.
   ```bash
   cd ..
   git clone https://github.com/intersystems-community/iris-devtester.git
   cd iris-devtester
   pip install -e .
   ```

## Running Tests
You no longer need to manually run `docker-compose up`. Simply run `pytest`:

```bash
# Run all tests (automatically starts IRIS)
pytest

# Run with specific IRIS image
pytest --iris-image=intersystems/iris-community:2025.1.0

# Run only integration tests
pytest tests/integration/ -v
```

## Using the Agentic Skills (Slash Commands)
If you are using **Claude Code**, you can invoke the skills directly:

- **`/container`**: Manage your test container.
- **`/connection`**: Debug your database connection.
- **`/fixture`**: Load test data.
- **`/troubleshooting`**: Diagnose test failures.

## Writing a New Test
The framework provides high-level fixtures:

```python
def test_my_new_feature(iris_connection):
    # iris_connection is already connected and ready
    with iris_connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone()[0] == 1

def test_with_data(iris_fixture, iris_connection):
    # Load specific data set
    iris_fixture.load("healthcare_data.dat")
    
    with iris_connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM Patients")
        assert cursor.fetchone()[0] > 0
```

## Troubleshooting Failures
On failure, check `test_failures.jsonl` in the project root for detailed diagnostics and remediation steps.
