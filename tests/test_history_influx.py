"""Tests for InfluxDBGenerationLoader CSV parsing."""

from datetime import UTC, datetime

from solar_forecast.history import InfluxDBGenerationLoader

SAMPLE = """#datatype,string,long,dateTime:RFC3339,double
#group,false,false,false,false
#default,_result,,,,,
,result,table,_start,_stop,_time,_value
,_result,0,2026-08-23T00:00:00Z,2026-08-23T01:00:00Z,2026-08-23T00:15:00Z,200.5
,_result,0,2026-08-23T00:00:00Z,2026-08-23T01:00:00Z,2026-08-23T00:30:00Z,400.0
#datatype,string,long,dateTime:RFC3339,double
#group,false,false,false,false
#default,_result,,,,
,result,table,_start,_stop,_time,_value
,_result,1,2026-08-23T00:00:00Z,2026-08-23T01:00:00Z,2026-08-23T00:45:00Z,100.0
"""


def test_parse_csv_multi_table() -> None:
    rows = InfluxDBGenerationLoader()._parse_csv(SAMPLE)
    assert len(rows) == 3
    times = [t for t, _ in rows]
    values = [v for _, v in rows]
    assert values == [200.5, 400.0, 100.0]
    assert times[0] == datetime(2026, 8, 23, 0, 15, tzinfo=UTC)


def test_energy_conversion() -> None:
    # 200 W mean over 15 min -> 50 Wh
    loader = InfluxDBGenerationLoader()
    assert loader.window_minutes * 60 / 3600 == 0.25


def test_parse_csv_garbage_rows_skipped() -> None:
    rows = InfluxDBGenerationLoader()._parse_csv("junk\n")
    assert rows == []
