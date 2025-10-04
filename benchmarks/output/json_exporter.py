"""
JSON export for benchmark results (T021, FR-010).

Exports benchmark results as JSON files.
"""

import json
from pathlib import Path
from datetime import datetime

from benchmarks.config import BenchmarkReport


def export_json(report: BenchmarkReport, output_dir: str = "benchmarks/results/json") -> str:
    """
    Export benchmark report as JSON file.

    Args:
        report: BenchmarkReport to export
        output_dir: Directory for JSON output

    Returns:
        Path to created JSON file

    Example:
        >>> report = BenchmarkReport(...)
        >>> filepath = export_json(report)
        >>> # Creates: benchmarks/results/json/benchmark_TIMESTAMP.json
    """
    # Ensure output directory exists
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Generate filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"benchmark_{timestamp}.json"
    filepath = output_path / filename

    # Export to JSON
    json_data = report.to_json()

    with open(filepath, 'w') as f:
        json.dump(json_data, f, indent=2)

    return str(filepath)
