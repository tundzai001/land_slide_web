"""Add streaming Excel workbooks to the existing scoped CSV export archive."""
import csv
import io
import os
import tempfile
import zipfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell


def _format_cell_values(row: list[str], sheet) -> list[WriteOnlyCell]:
    cells = []
    for value in row:
        if len(value) > 32767:
            value = value[:32700] + '... [TRUNCATED - xem file CSV để có đầy đủ]'
        cell = WriteOnlyCell(sheet, value=value)
        cell.data_type = 's'  # Sensor strings must never become executable formulas.
        cells.append(cell)
    return cells


def _convert_csv_to_workbook(handle) -> Workbook:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet('Data_1')
    sheets, count, headers = 1, 0, None
    for row in csv.reader(handle):
        if headers is None:
            headers = row
        if count >= 1048576:
            sheets += 1
            sheet = workbook.create_sheet(f'Data_{sheets}')
            sheet.append(headers)
            count = 1
        sheet.append(_format_cell_values(row, sheet))
        count += 1
    return workbook


def _write_workbook_to_archive(workbook: Workbook, path: str, name: str):
    with tempfile.TemporaryDirectory(dir=os.path.dirname(path)) as directory:
        output = Path(directory) / 'data.xlsx'
        workbook.save(output)
        with zipfile.ZipFile(path, 'a', zipfile.ZIP_DEFLATED, compresslevel=1) as target:
            target.write(output, name[:-4] + '.xlsx')


def add_excel_files(path):
    # One CSV dataset per workbook; split sheets at Excel's hard row limit.
    with zipfile.ZipFile(path, 'r') as source:
        names = [name for name in source.namelist() if name.lower().endswith('.csv')]
    for name in names:
        with zipfile.ZipFile(path, 'r') as source:
            with source.open(name) as binary, io.TextIOWrapper(binary, encoding='utf-8-sig', newline='') as handle:
                workbook = _convert_csv_to_workbook(handle)
        _write_workbook_to_archive(workbook, path, name)
