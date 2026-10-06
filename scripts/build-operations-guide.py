"""Build the downloadable operations manual: python scripts/build-operations-guide.py.

Requires ReportLab (already in backend requirements). The checked-in PDF is served
as an attachment; no PDF generation or fonts are needed on the production server.
"""
import html
import json
import re
import shutil
import textwrap
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted

ROOT = Path(__file__).resolve().parents[1]
FONTS = [
    ('/System/Library/Fonts/Supplemental/Arial.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf'),
    ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
    ('C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/arialbd.ttf'),
]
regular, bold = next((pair for pair in FONTS if all(Path(p).is_file() for p in pair)), (None, None))
if regular is None:
    raise SystemExit('Install Arial or DejaVu Sans to generate the Vietnamese manual.')
pdfmetrics.registerFont(TTFont('Guide', regular))
pdfmetrics.registerFont(TTFont('GuideBold', bold))
pdfmetrics.registerFontFamily('Guide', normal='Guide', bold='GuideBold', italic='Guide', boldItalic='GuideBold')
TEAL = colors.HexColor('#357c78')
body = ParagraphStyle('body', fontName='Guide', fontSize=10, leading=15, spaceAfter=8, textColor=colors.HexColor('#253b40'))
title = ParagraphStyle('title', parent=body, fontName='GuideBold', fontSize=23, leading=29, textColor=TEAL, spaceAfter=22)
heading = ParagraphStyle('heading', parent=body, fontName='GuideBold', fontSize=14, leading=19, textColor=TEAL, spaceBefore=15, spaceAfter=9, keepWithNext=True)
subheading = ParagraphStyle('subheading', parent=heading, fontSize=11, leading=16)
code_style = ParagraphStyle('code', parent=body, fontSize=8, leading=11, leftIndent=10, rightIndent=10, backColor=colors.HexColor('#eef5f4'), borderPadding=8, spaceBefore=6, spaceAfter=12)


def inline(text):
    text = html.escape(text.replace('→', '->').replace('–', '-').replace('—', '-'))
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    return re.sub(r'`([^`]+)`', r'<font color="#357c78">\1</font>', text)


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor('#d5e3e1'))
    canvas.line(44, 37, A4[0] - 44, 37)
    canvas.setFont('Guide', 8)
    canvas.setFillColor(colors.HexColor('#60787d'))
    canvas.drawString(44, 24, 'LANDSLIDE MONITOR | Hướng dẫn vận hành & tích hợp')
    canvas.drawRightString(A4[0] - 44, 24, str(doc.page))
    canvas.restoreState()


story, code = [], None
for line in (ROOT / 'docs/OPERATIONS_INTEGRATION.md').read_text().splitlines():
    if line.startswith('```'):
        if code is None:
            code = []
        else:
            text = '\n'.join(code)
            try:
                text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
            except ValueError:
                pass
            wrapped = '\n'.join(textwrap.fill(row, width=95, replace_whitespace=False, drop_whitespace=False) for row in text.splitlines())
            story.append(Preformatted(wrapped, code_style))
            code = None
        continue
    if code is not None:
        code.append(line)
    elif not line.strip():
        continue
    elif line.startswith('# '):
        story.extend([Paragraph('TÀI LIỆU QUẢN TRỊ', subheading), Paragraph(inline(line[2:]), title)])
    elif line.startswith('## '):
        story.append(Paragraph(inline(line[3:]), heading))
    elif line.startswith('### '):
        story.append(Paragraph(inline(line[4:]), subheading))
    else:
        story.append(Paragraph(inline(line), body))
output = ROOT / 'output/pdf/huong-dan-van-hanh-tich-hop.pdf'
output.parent.mkdir(parents=True, exist_ok=True)
SimpleDocTemplate(str(output), pagesize=A4, leftMargin=44, rightMargin=44,
                  topMargin=40, bottomMargin=52, title='Landslide Monitor - Hướng dẫn vận hành và tích hợp',
                  author='Aitogy').build(story, onFirstPage=footer, onLaterPages=footer)
shutil.copyfile(output, ROOT / 'docs/OPERATIONS_INTEGRATION.pdf')
print(output)
