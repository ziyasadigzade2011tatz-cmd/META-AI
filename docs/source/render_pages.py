from pathlib import Path
import pypdfium2 as pdfium

root=Path(__file__).resolve().parent
pdf=pdfium.PdfDocument(root/'report_preview.pdf')
for index,page in enumerate(pdf):
    page.render(scale=1.6).to_pil().save(root/f'page-{index+1}.png')
    text=page.get_textpage().get_text_range()
    print(f'Page {index+1}: {len(text)} chars; '+text[:70].replace('\r',' ').replace('\n',' '))
print('Pages:',len(pdf))
