import os
import sys

# Add src to path exactly as the pytest command does
sys.path.insert(0, os.path.abspath("src"))

try:
    import iris_pgwire.iris_executor as executor

    print(f"iris_executor found at: {executor.__file__}")

    # Check for the fix in the file
    with open(executor.__file__) as f:
        content = f.read()
        if "captured_sql" in content:
            print("Fix verified in the loaded file.")
        else:
            print("Fix NOT FOUND in the loaded file!")

except Exception as e:
    print(f"Error: {e}")
