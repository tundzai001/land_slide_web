import sys
sys.stdout.reconfigure(encoding='utf-8')

with open(r'c:\Users\len\Desktop\tun\land_slide_web\frontend\css\admin.css', 'rb') as f:
    data = f.read()

print(f'Size: {len(data)} bytes')
print(f'Has null bytes: {b"\x00" in data}')

text = data.decode('utf-8', errors='replace')
opens = text.count('{')
closes = text.count('}')
print(f'Braces open: {opens}, close: {closes}, balanced: {opens == closes}')
print(f'Has .wizard-steps: {".wizard-steps" in text}')
print(f'Has .step-circle: {".step-circle" in text}')
print(f'Has .wizard-step.active: {".wizard-step.active" in text}')

# Find unmatched braces
depth = 0
for i, ch in enumerate(text):
    if ch == '{':
        depth += 1
    elif ch == '}':
        depth -= 1
    if depth < 0:
        line = text[:i].count('\n') + 1
        print(f'ERROR: Extra closing brace at line {line}')
        break
if depth > 0:
    print(f'ERROR: {depth} unclosed braces at end of file')
elif depth == 0:
    print('CSS brace structure is valid')
