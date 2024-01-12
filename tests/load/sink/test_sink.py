from typing import List, Tuple

import dlt
import pytest

from copy import deepcopy
from dlt.common.typing import TDataItems
from dlt.common.schema import TTableSchema
from dlt.common.data_writers.writers import TLoaderFileFormat

from tests.load.utils import (
    TABLE_ROW_ALL_DATA_TYPES,
    TABLE_UPDATE_COLUMNS_SCHEMA,
    assert_all_data_types_row,
    delete_dataset,
)

SUPPORTED_LOADER_FORMATS = ["parquet", "jsonl"]


def _run_through_sink(
    items: TDataItems,
    loader_file_format: TLoaderFileFormat,
    columns=None,
    filter_dlt_tables: bool = True,
    batch_size: int = 10,
) -> List[Tuple[TDataItems, TTableSchema]]:
    """
    runs a list of items through the sink destination and returns colleceted calls
    """
    calls: List[Tuple[TDataItems, TTableSchema]] = []

    @dlt.sink(loader_file_format=loader_file_format, batch_size=batch_size)
    def test_sink(items: TDataItems, table: TTableSchema) -> None:
        nonlocal calls
        if table["name"].startswith("_dlt") and filter_dlt_tables:
            return
        calls.append((items, table))

    @dlt.resource(columns=columns, table_name="items")
    def items_resource() -> TDataItems:
        nonlocal items
        yield items

    p = dlt.pipeline("sink_test", destination=test_sink, full_refresh=True)
    p.run([items_resource()])

    return calls


@pytest.mark.parametrize("loader_file_format", SUPPORTED_LOADER_FORMATS)
def test_all_datatypes(loader_file_format: TLoaderFileFormat) -> None:
    data_types = deepcopy(TABLE_ROW_ALL_DATA_TYPES)
    column_schemas = deepcopy(TABLE_UPDATE_COLUMNS_SCHEMA)

    sink_calls = _run_through_sink(
        [data_types, data_types, data_types],
        loader_file_format,
        columns=column_schemas,
        batch_size=1,
    )

    # inspect result
    assert len(sink_calls) == 3

    item = sink_calls[0][0]
    # filter out _dlt columns
    item = {k: v for k, v in item.items() if not k.startswith("_dlt")}  # type: ignore

    # null values are not emitted
    data_types = {k: v for k, v in data_types.items() if v is not None}

    # check keys are the same
    assert set(item.keys()) == set(data_types.keys())

    assert_all_data_types_row(item, expect_filtered_null_columns=True)


@pytest.mark.parametrize("loader_file_format", SUPPORTED_LOADER_FORMATS)
@pytest.mark.parametrize("batch_size", [1, 10, 23])
def test_batch_size(loader_file_format: TLoaderFileFormat, batch_size: int) -> None:
    items = [{"id": i, "value": str(i)} for i in range(100)]

    sink_calls = _run_through_sink(items, loader_file_format, batch_size=batch_size)

    if batch_size == 1:
        assert len(sink_calls) == 100
        # one item per call
        assert sink_calls[0][0].items() > {"id": 0, "value": "0"}.items()  # type: ignore
    elif batch_size == 10:
        assert len(sink_calls) == 10
        # ten items in first call
        assert len(sink_calls[0][0]) == 10
        assert sink_calls[0][0][0].items() > {"id": 0, "value": "0"}.items()
    elif batch_size == 23:
        assert len(sink_calls) == 5
        # 23 items in first call
        assert len(sink_calls[0][0]) == 23
        assert sink_calls[0][0][0].items() > {"id": 0, "value": "0"}.items()

    # check all items are present
    all_items = set()
    for call in sink_calls:
        item = call[0]
        if batch_size == 1:
            item = [item]
        for entry in item:
            all_items.add(entry["value"])

    assert len(all_items) == 100
    for i in range(100):
        assert str(i) in all_items