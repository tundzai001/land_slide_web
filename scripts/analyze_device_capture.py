"""Summarize complete sentences reassembled from a read-only MQTT capture."""
import json
import re
from collections import Counter
from pathlib import Path

capture_file = Path(__file__).resolve().parent / 'probes' / 'mqtt_device_capture.json'
if not capture_file.is_file():
    capture_file = Path('mqtt_device_capture.json').resolve()
if not capture_file.is_file():
    raise FileNotFoundError(f"Missing capture file: {capture_file}")
with open(capture_file, 'r', encoding='utf-8') as f:
    records = json.load(f)
stream = ''.join(row['payload'] for row in records)
sentences = re.findall(r'[$#][^$#\r\n]*\*[0-9a-fA-F]+', stream)
print('Sentence types:', Counter(s.split(',')[0] for s in sentences))
rows = []
for sentence in sentences:
    if not sentence.startswith('#AGRICA'):
        continue
    body, checksum = sentence[1:].rsplit('*', 1)
    crc = 0
    for byte in body.encode('ascii'):
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xEDB88320 if crc & 1 else 0)
    if crc != int(checksum, 16):
        print('CRC mismatch')
        continue
    rows.append(body.split(';')[1].split(','))
print('CRC-valid AGRICA:', len(rows))
fields = {8:'position_type', 13:'baseline_N',14:'baseline_E',15:'baseline_U',16:'baseline_std_N',17:'baseline_std_E',18:'baseline_std_U',22:'speed',23:'velocity_N',24:'velocity_E',25:'velocity_U',26:'velocity_std_N',27:'velocity_std_E',28:'velocity_std_U',29:'latitude',30:'longitude',31:'altitude',35:'latitude_std',36:'longitude_std',37:'altitude_std',41:'base_lat',42:'base_lon',43:'base_alt',48:'diff_age',50:'undulation',54:'speed_type'}
for index, name in fields.items():
    values = [float(row[index]) for row in rows]
    print(name, 'first=',values[0], 'range=', min(values), max(values))
for row in rows:
    if max(float(v) for v in row[16:19]) > 0.1:
        print('uncertain baseline epoch', row[5:8], 'status',row[8], 'baseline',row[13:16], 'std', row[16:19], 'age',row[48])
out_file = capture_file.parent / 'mqtt_device_sentences.txt'
with open(out_file, 'w', encoding='utf-8') as f:
    f.write('\n'.join(sentences))
