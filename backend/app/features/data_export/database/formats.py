"""Add streaming Excel workbooks to the existing scoped CSV export archive."""
import csv
import io
import os
import tempfile
import zipfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell


def add_excel_files(path):
    # One CSV dataset per workbook; split sheets at Excel's hard row limit.
    with zipfile.ZipFile(path, 'r') as source:
        names = [name for name in source.namelist() if name.lower().endswith('.csv')]
    for name in names:
        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet('Data_1')
        sheets, count, headers = 1, 0, None
        with zipfile.ZipFile(path, 'r') as source:
            with source.open(name) as binary, io.TextIOWrapper(binary, encoding='utf-8-sig', newline='') as handle:
                for row in csv.reader(handle):
                    if headers is None:
                        headers = row
                    if count >= 1048576:
                        sheets += 1
                        sheet = workbook.create_sheet(f'Data_{sheets}')
                        sheet.append(headers)
                        count = 1
                    cells = []
                    for value in row:
                        if len(value) > 32767:
                            raise ValueError('A CSV field exceeds the Excel cell limit; choose CSV to preserve the full value')
                        cell = WriteOnlyCell(sheet, value=value)
                        cell.data_type = 's'  # Sensor strings must never become executable formulas.
                        cells.append(cell)
                    sheet.append(cells)
                    count += 1
        with tempfile.TemporaryDirectory(dir=os.path.dirname(path)) as directory:
            output = Path(directory) / 'data.xlsx'
            workbook.save(output)
            with zipfile.ZipFile(path, 'a', zipfile.ZIP_DEFLATED, compresslevel=1) as target:
                target.write(output, name[:-4] + '.xlsx')
