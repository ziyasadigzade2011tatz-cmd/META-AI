"""One real local vision probe with a generated test card, not a user photo."""
import base64,json,os,re,sys,time,struct,zlib
from pathlib import Path
repo=Path(__file__).resolve().parents[2];folder=repo/'build/code-upgrade';folder.mkdir(parents=True,exist_ok=True)
os.environ['META5_STATE']=str(folder/'vision-state');sys.path.insert(0,str(repo/'studio/core'))
from meta5.image_context import analyze
pixels=[bytearray(b'\xff\xff\xff'*640) for _ in range(360)]
for y in range(100,320):
    for x in range(25,280):pixels[y][x*3:x*3+3]=b'\x00\x00\xff'
for y in range(110,320):
    for x in range(360,570):
        if (x-465)**2+(y-215)**2<=105**2:pixels[y][x*3:x*3+3]=b'\xff\x00\x00'
glyphs={'M':['10001','11011','10101','10101','10001','10001','10001'],'E':['11111','10000','10000','11110','10000','10000','11111'],'T':['11111','00100','00100','00100','00100','00100','00100'],'A':['01110','10001','10001','11111','10001','10001','10001'],'4':['10010','10010','10010','11111','00010','00010','00010'],'2':['01110','10001','00001','00010','00100','01000','11111']}
for i,char in enumerate('META 42'):
    for gy,line in enumerate(glyphs.get(char,[])):
        for gx,bit in enumerate(line):
            if bit=='1':
                for y in range(20+gy*8,28+gy*8):
                    for x in range(25+i*55+gx*8,33+i*55+gx*8):pixels[y][x*3:x*3+3]=b'\x00\x00\x00'
def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',640,360,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(b'\x00'+bytes(row) for row in pixels)))+chunk(b'IEND',b'')
path=folder/'vision-card.png';path.write_bytes(png)
started=time.monotonic();result=analyze('data:image/png;base64,'+base64.b64encode(path.read_bytes()).decode(),'Прочитай надпись и перечисли цвета и фигуры.')
text=result['observations_untrusted'];passed=bool(re.search(r'\b42\b',text))
report={'passed_text_42':passed,'model':result['model'],'seconds':round(time.monotonic()-started,3),'synthetic_observations':text,'scope':'One synthetic local image; no claim of universal OCR accuracy'}
(folder/'vision-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(report,ensure_ascii=False))
if not passed:raise SystemExit(1)
