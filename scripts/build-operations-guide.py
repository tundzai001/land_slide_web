"""Build integration PDF, or web user PDF with --user: python scripts/build-operations-guide.py.

Requires ReportLab (already in backend requirements). The checked-in PDF is served
as an attachment; no PDF generation or fonts are needed on the production server.
"""
import argparse
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
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted, Image, PageBreak

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--user', action='store_true', help='Build the illustrated web user guide')
args = parser.parse_args()
source = ROOT / ('docs/USER_GUIDE.md' if args.user else 'docs/OPERATIONS_INTEGRATION.md')
manual_title = 'Hướng dẫn sử dụng web' if args.user else 'Hướng dẫn vận hành & tích hợp'
filename = 'huong-dan-su-dung-web.pdf' if args.user else 'huong-dan-van-hanh-tich-hop.pdf'
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
if args.user:
    body.fontSize, body.leading = 11, 17
    title.fontSize, title.leading = 32, 38
    heading.fontSize, heading.leading = 19, 25
    subheading.fontSize, subheading.leading = 12, 18

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
    canvas.drawString(44, 24, f'LANDSLIDE MONITOR | {manual_title}')
    canvas.drawRightString(A4[0] - 44, 24, str(doc.page))
    canvas.restoreState()


story, code = [], None
for line in source.read_text().splitlines():
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
    elif args.user and line == '---':
        story.append(PageBreak())
    elif args.user and line.startswith('!['):
        caption, relative = re.fullmatch(r'!\[(.*?)\]\((.*?)\)', line).groups()
        picture = Image(str(source.parent / relative))
        scale = min(507 / picture.imageWidth, 245 / picture.imageHeight)
        picture.drawWidth = picture.imageWidth * scale
        picture.drawHeight = picture.imageHeight * scale
        picture.hAlign = 'LEFT'
        story.extend([Spacer(1, 10), picture, Spacer(1, 7), Paragraph(inline(caption), ParagraphStyle('caption', parent=body, fontSize=8, leading=11, textColor=colors.HexColor('#60787d'))), Spacer(1, 12)])
    elif line.startswith('# '):
        story.extend([Paragraph('CẨM NANG THAO TÁC' if args.user else 'TÀI LIỆU QUẢN TRỊ', subheading), Paragraph(inline(line[2:]), title)])
    elif line.startswith('## '):
        story.append(Paragraph(inline(line[3:]), heading))
    elif line.startswith('### '):
        story.append(Paragraph(inline(line[4:]), subheading))
    else:
        story.append(Paragraph(inline(line), body))
output = ROOT / 'output/pdf' / filename
output.parent.mkdir(parents=True, exist_ok=True)
SimpleDocTemplate(str(output), pagesize=A4, leftMargin=44, rightMargin=44,
                  topMargin=40, bottomMargin=52, title=f'Landslide Monitor - {manual_title}',
                  author='Aitogy').build(story, onFirstPage=footer, onLaterPages=footer)
shutil.copyfile(output, ROOT / ('docs/USER_GUIDE.pdf' if args.user else 'docs/OPERATIONS_INTEGRATION.pdf'))
print(output)
