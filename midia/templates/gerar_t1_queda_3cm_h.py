# -*- coding: utf-8 -*-
"""04/11/2026: versão horizontal (1200x628, ~1.91:1) da imagem do T1 resgate_queda_3cm_v2, para o WhatsApp não cortar
o rosto da Dra. Luciana nem o texto. Recomposta a partir da arte vertical da clínica (midia/templates/t1_queda_3cm.jpg)."""
import sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter
sys.stdout.reconfigure(encoding="utf-8")
SRC = r"C:\Users\Administrativo\Desktop\Arquivos PBIP\passoni-ia-atendimento\midia\templates\t1_queda_3cm.jpg"
OUT = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\ADMINI~1\AppData\Local\Temp\claude\2748e684b82f4fe2\c7516241-e84d-4bc8-a364-199c6293c0d9\scratchpad\t1_queda_3cm_h.jpg"
W, H = 1200, 628
BG = (26, 20, 16)
INK = (246, 240, 232)
GOLD = (227, 201, 160)
MUTED = (200, 190, 178)
F = "C:/Windows/Fonts/"
def font(name, size): return ImageFont.truetype(F + name, size)

src = Image.open(SRC).convert("RGB")
# recorte do rosto: região central da foto, proporção do painel esquerdo
PW = 600                      # largura do painel da foto
x0, y0, x1, y1 = 545, 60, 1558, 1120    # 1013 x 1060 ≈ 600 x 628; cabeça inteira, sem o logo original (x<540) nem o 'VOCÊ SABIA?' (y>1180)
foto = src.crop((x0, y0, x1, y1)).resize((PW, H), Image.LANCZOS)
im = Image.new("RGB", (W, H), BG)
im.paste(foto, (0, 0))
# degradê da foto para o fundo escuro (lado direito do painel) e um leve escurecimento na base
grad = Image.new("L", (PW, H), 0)
gd = ImageDraw.Draw(grad)
for x in range(PW):
    a = 0 if x < 400 else int(255 * ((x - 400) / 200) ** 1.4)
    gd.line([(x, 0), (x, H)], fill=min(255, a))
im.paste(Image.new("RGB", (PW, H), BG), (0, 0), grad)
base = Image.new("L", (PW, H), 0); bd = ImageDraw.Draw(base)
for y in range(H):
    a = 0 if y < 470 else int(200 * ((y - 470) / 158) ** 1.3)
    bd.line([(0, y), (PW, y)], fill=min(255, a))
im.paste(Image.new("RGB", (PW, H), BG), (0, 0), base)

# vinheta suave na borda esquerda (esconde a emenda do remendo e enquadra a foto)
vin = Image.new('L', (PW, H), 0); vd = ImageDraw.Draw(vin)
for x in range(90):
    vd.line([(x, 0), (x, H)], fill=int(150 * (1 - x / 90) ** 1.6))
im.paste(Image.new('RGB', (PW, H), BG), (0, 0), vin)
d = ImageDraw.Draw(im)
def tracked(x, y, txt, fnt, fill, track):
    for ch in txt:
        d.text((x, y), ch, font=fnt, fill=fill)
        x += d.textlength(ch, font=fnt) + track
    return x

L = 640   # margem esquerda do texto
# logo
tracked(L, 44, "PASSONI", font("georgia.ttf", 40), INK, 10)
d.line([(L, 104), (L + 60, 104)], fill=MUTED, width=1)
tracked(L + 74, 92, "CLINIC", font("segoeui.ttf", 18), MUTED, 8)
d.line([(L + 190, 104), (L + 250, 104)], fill=MUTED, width=1)
# chamada
tracked(L, 166, "VOCÊ SABIA?", font("segoeui.ttf", 20), MUTED, 7)
h1 = font("georgia.ttf", 50); h1i = font("georgiai.ttf", 50)
d.text((L, 204), "Um fio saudável cresce", font=h1, fill=INK)
x = L
d.text((x, 266), "3 cm", font=h1i, fill=GOLD); x += d.textlength("3 cm", font=h1i) + 14
d.text((x, 266), "em 3 meses.", font=h1, fill=INK)
# régua
rx0, rx1, ry = L, W - 56, 392
d.line([(rx0, ry), (rx1, ry)], fill=MUTED, width=2)
for i in range(13):
    xx = rx0 + (rx1 - rx0) * i / 12
    d.line([(xx, ry), (xx, ry + (14 if i % 4 == 0 else 7))], fill=MUTED, width=2)
fs = font("segoeui.ttf", 18); fb = font("segoeuib.ttf", 18)
for i, (t, f_) in enumerate([("hoje", fs), ("1 mês", fs), ("2 meses", fs), ("3 meses · 3 cm", fb)]):
    xx = rx0 + (rx1 - rx0) * i / 3
    tw = d.textlength(t, font=f_)
    ax = xx if i == 0 else (xx - tw if i == 3 else xx - tw / 2)
    d.text((ax, ry + 22), t, font=f_, fill=INK if i == 3 else MUTED)
# rodapé
d.text((L, 500), "Como estão seus cabelos hoje?", font=font("segoeuib.ttf", 26), fill=INK)
nome = font("georgia.ttf", 30); tw = d.textlength("Dra. Luciana Passoni", font=nome)
d.text((W - 56 - tw, 548), "Dra. Luciana Passoni", font=nome, fill=INK)
sub = font("segoeui.ttf", 15); st = "PASSONI CLINIC"
sw = sum(d.textlength(c, font=sub) + 6 for c in st) - 6
tracked(W - 56 - sw, 590, st, sub, MUTED, 6)
im.save(OUT, "JPEG", quality=92)
print("ok", OUT, im.size)
