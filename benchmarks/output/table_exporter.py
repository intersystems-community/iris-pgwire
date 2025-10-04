"""
Console table export for benchmark results (T022, FR-010).

Exports benchmark results as formatted console tables using tabulate.
"""

from pathlib import Path
from datetime import datetime
from tabulate import tabulate

from benchmarks.config import BenchmarkReport


def export_table(report: BenchmarkReport, output_dir: str = "benchmarks/results/tables") -> str:
    """
    Export benchmark report as formatted table.

    Args:
        report: BenchmarkReport to export
        output_dir: Directory for table output (also saves to file)

    Returns:
        Formatted table string

    Example:
        >>> report = BenchmarkReport(...)
        >>> table = export_table(report)
        >>> print(table)
        Method                 QPS      P50 (ms)  P95 (ms)  P99 (ms)
        -------------------  -------  ----------  --------  --------
        IRIS + PGWire        1234.5        8.3      12.7      15.9
        ...
    """
    # Get table rows from report
    rows = report.to_table_rows()

    # Define headers
    headers = ["Method", "QPS", "P50 (ms)", "P95 (ms)", "P99 (ms)"]

    # Format table
    table_str = tabulate(rows, headers=headers, tablefmt="simple", floatfmt=".2f")

    # Add header information
    output = []
    output.append("=" * 70)
    output.append("3-Way Database Performance Benchmark")
    output.append("=" * 70)
    output.append(f"Report ID: {report.report_id}")
    output.append(f"Timestamp: {report.start_time.isoformat()}")
    output.append("")
    output.append("Configuration:")
    output.append(f"  Vector Dimensions:  {report.config.vector_dimensions}")
    output.append(f"  Dataset Size:       {report.config.dataset_size:,} rows")
    output.append(f"  Iterations:         {report.config.iterations}")
    output.append("")
    output.append("Results:")
    output.append(table_str)
    output.append("")
    output.append(f"Benchmark completed in {report.total_duration_seconds:.2f} seconds.")
    output.append("=" * 70)

    full_output = "\n".join(output)

    # Save to file
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"benchmark_{timestamp}.txt"
    filepath = output_path / filename

    with open(filepath, 'w') as f:
        f.write(full_output)

    return full_output
