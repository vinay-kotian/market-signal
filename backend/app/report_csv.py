"""Bounded CSV serialization of persisted report fields."""
import csv
from io import StringIO


CSV_FIELDS = (
    'trade_id', 'trade_mode', 'instrument', 'option_symbol', 'direction',
    'entry_time', 'exit_time', 'entry_price', 'highest_price', 'exit_price',
    'quantity', 'realised_pnl', 'realised_pnl_percentage', 'exit_reason', 'status',
    'trigger_level', 'validity_status', 'validity_reason',
    'exclude_from_strategy_metrics',
)


def safe_cell(value):
    # Protect text, including formulas hidden behind whitespace/control bytes.
    # Preserve numeric negatives as numbers for P&L reconciliation.
    if isinstance(value, str) and (
        value.lstrip().startswith(('=', '+', '-', '@'))
        or value.startswith(('\t', '\r', '\n'))
    ):
        return "'" + value
    return value


def csv_chunks(rows):
    buffer = StringIO(newline='')
    writer = csv.writer(buffer)
    try:
        writer.writerow(CSV_FIELDS)
        yield buffer.getvalue()
        for row in rows:
            buffer.seek(0)
            buffer.truncate(0)
            writer.writerow([safe_cell(row[field]) for field in CSV_FIELDS])
            yield buffer.getvalue()
    finally:
        rows.close()
        buffer.close()
