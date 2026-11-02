"""Render synthetic claims to PDFs (digital) and noisy PNG "scans", plus a manifest with ground truth.

Layouts differ per document source on purpose (three repair shops' invoice templates, two claim-form versions), because
layout variation is what makes extraction hard in real intake.
"""

import json
import random
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageFilter
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from claimdesk.synth import Claim

FONTS = Path(__file__).parent / "assets" / "fonts"
for _name, _file in [("Sans", "DejaVuSans"), ("SansB", "DejaVuSans-Bold"), ("Serif", "DejaVuSerif"), ("SerifB", "DejaVuSerif-Bold"),
                     ("Mono", "DejaVuSansMono")]:
    pdfmetrics.registerFont(TTFont(_name, str(FONTS / f"{_file}.ttf")))

W, H = A4
INK, GREY, BLUE = HexColor("#1b2733"), HexColor("#6b7680"), HexColor("#1f4e79")
L = {
    "hu": {"form": "GÉPJÁRMŰ KÁRBEJELENTŐ LAP", "policy": "Kötvényszám", "name": "Bejelentő neve", "address": "Lakcím", "phone": "Telefon",
           "email": "E-mail", "plate": "Rendszám", "vehicle": "Gyártmány, típus", "when": "Káresemény időpontja",
           "where": "Káresemény helyszíne", "what": "A káresemény leírása", "estimate": "Becsült kárösszeg (Ft)",
           "iban": "Bankszámlaszám (kifizetéshez)", "signed": "Kelt", "sign": "aláírás",
           "eas": "EURÓPAI BALESETI BEJELENTŐ", "date": "Dátum", "time": "Időpont", "loc": "Helyszín", "veh": "Jármű",
           "insurer": "Biztosító", "driver": "Vezető", "circ": "Körülmények", "inj": "Személyi sérülés", "wit": "Tanúk", "yes": "igen", "no": "nem"},
    "en": {"form": "MOTOR CLAIM NOTIFICATION FORM", "policy": "Policy number", "name": "Name of claimant", "address": "Address", "phone": "Phone",
           "email": "E-mail", "plate": "Registration number", "vehicle": "Make and model", "when": "Date and time of loss",
           "where": "Place of loss", "what": "Description of the incident", "estimate": "Estimated damage (HUF)",
           "iban": "Bank account (IBAN) for payment", "signed": "Date", "sign": "signature",
           "eas": "EUROPEAN ACCIDENT STATEMENT", "date": "Date", "time": "Time", "loc": "Location", "veh": "Vehicle",
           "insurer": "Insurer", "driver": "Driver", "circ": "Circumstances", "inj": "Injuries", "wit": "Witnesses", "yes": "yes", "no": "no"},
}
CIRCUMSTANCES = ["álló helyzetben volt", "parkolóhelyről kiállt", "egyenesen haladt", "sávot váltott", "hátulról ütközött",
                 "kanyarodott", "tolatott", "elsőbbséget nem adott"]


def huf(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _wrap(c: Canvas, text: str, x: float, y: float, width: float, font: str, size: float, lead: float) -> float:
    words, line = text.split(), ""
    for w in words:
        if c.stringWidth(f"{line} {w}".strip(), font, size) > width:
            c.drawString(x, y, line)
            y, line = y - lead, w
        else:
            line = f"{line} {w}".strip()
    c.drawString(x, y, line)
    return y - lead


def claim_form(c: Canvas, cl: Claim, f: dict, layout: str) -> None:
    t = L[cl.lang]
    c.setFillColor(BLUE)
    c.setFont("SansB", 17)
    c.drawString(40, H - 60, "Kékhíd Biztosító Zrt.")
    c.setFont("Sans", 8)
    c.setFillColor(GREY)
    c.drawString(40, H - 74, "1138 Budapest, Kékhíd utca 1. · kar@kekhid.example · +36 1 555 0100")
    c.setFillColor(INK)
    c.setFont("SansB", 13)
    c.drawString(40, H - 110, t["form"])
    rows = [("policy", f["policy_number"]), ("name", f["claimant_name"]), ("address", f["address"]), ("phone", f["phone"]),
            ("email", f["email"]), ("plate", f["plate"]), ("vehicle", f["vehicle"]),
            ("when", f["loss_datetime"].replace("T", " ")), ("where", f["loss_location"]), ("estimate", huf(f["estimated_amount_huf"])),
            ("iban", f["payout_iban"])]
    y = H - 145
    for key, val in rows:
        if layout == "form_a":  # boxed grid
            c.setStrokeColor(GREY)
            c.rect(40, y - 8, W - 80, 24, stroke=1, fill=0)
            c.setFont("Sans", 7)
            c.setFillColor(GREY)
            c.drawString(46, y + 8, t[key])
            c.setFillColor(INK)
            c.setFont("Mono", 10)
            c.drawString(46, y - 3, str(val))
            y -= 30
        else:  # label: dotted value
            c.setFont("Sans", 9)
            c.drawString(40, y, f"{t[key]}:")
            c.setFont("Serif", 10.5)
            c.drawString(210, y, str(val))
            c.setStrokeColor(HexColor("#c9d0d6"))
            c.setDash(1, 2)
            c.line(205, y - 4, W - 40, y - 4)
            c.setDash()
            c.setStrokeColor(INK)
            y -= 22
    c.setFont("SansB" if layout == "form_a" else "Sans", 9)
    c.drawString(40, y - 6, t["what"] + ":")
    c.setFont("Mono" if layout == "form_a" else "Serif", 10)
    y = _wrap(c, f["description"], 40, y - 22, W - 80, "Mono" if layout == "form_a" else "Serif", 10, 14)
    c.setFont("Sans", 9)
    c.drawString(40, y - 30, f"{t['signed']}: {f['signed_date']}")
    c.line(W - 220, y - 30, W - 40, y - 30)
    c.setFont("Sans", 7)
    c.drawString(W - 160, y - 40, t["sign"])


def repair_invoice(c: Canvas, cl: Claim, f: dict, layout: str) -> None:
    serif = layout == "inv_b"
    head, body = ("SerifB", "Serif") if serif else ("SansB", "Sans")
    c.setFillColor(INK)
    if layout == "inv_a":
        c.setFont(head, 20)
        c.drawString(40, H - 60, "SZÁMLA")
        c.setFont(body, 9)
        c.drawRightString(W - 40, H - 50, f"Számla sorszáma: {f['invoice_number']}")
        c.drawRightString(W - 40, H - 63, f"Kelt: {f['issue_date']}   Teljesítés: {f['fulfilment_date']}")
        sx, bx, top = 40, W / 2 + 10, H - 100
    else:
        c.setFont(head, 13)
        c.drawString(40, H - 55, f["seller_name"])
        c.setFont(body, 8.5)
        c.drawString(40, H - 68, f"{cl.shop_city} · Adószám: {f['seller_tax_number']}")
        c.setFont(head, 16)
        c.drawRightString(W - 40, H - 55, "Számla" if layout == "inv_b" else "SZÁMLA / INVOICE")
        c.setFont(body, 8.5)
        c.drawRightString(W - 40, H - 70, f"Sorszám: {f['invoice_number']}")
        c.drawRightString(W - 40, H - 82, f"Számla kelte: {f['issue_date']}")
        c.drawRightString(W - 40, H - 94, f"Teljesítés dátuma: {f['fulfilment_date']}")
        sx, bx, top = None, 40, H - 125
    c.setFont(head, 9)
    if sx is not None:
        c.drawString(sx, top, "Eladó")
        c.setFont(body, 9)
        c.drawString(sx, top - 14, f["seller_name"])
        c.drawString(sx, top - 26, cl.shop_city)
        c.drawString(sx, top - 38, f"Adószám: {f['seller_tax_number']}")
        c.setFont(head, 9)
    c.drawString(bx, top, "Vevő")
    c.setFont(body, 9)
    c.drawString(bx, top - 14, f["buyer_name"])
    c.drawString(bx, top - 26, cl.address)
    c.drawString(bx, top - 38, f"Gépjármű rendszáma: {f['plate']}")
    y = top - 75
    cols = [40, 300, 350, 440] if layout != "inv_c" else [40, 290, 345, 445]
    heads = ["Megnevezés", "Menny.", "Egységár (Ft)", "Nettó (Ft)"] if layout != "inv_b" else ["Tétel", "db/óra", "Nettó egységár", "Nettó érték"]
    c.setFont(head, 8.5)
    for i, (x, h) in enumerate(zip(cols, heads, strict=True)):
        c.drawRightString(W - 40, y, h) if i == 3 else c.drawString(x, y, h)
    c.line(40, y - 4, W - 40, y - 4)
    c.setFont(body, 9)
    for li in f["line_items"]:
        y -= 17
        c.drawString(cols[0], y, li["description"])
        c.drawRightString(cols[1] + 30, y, str(li["quantity"]))
        c.drawRightString(cols[2] + 75, y, huf(li["unit_price_huf"]))
        c.drawRightString(W - 40, y, huf(li["net_huf"]))
    c.line(40, y - 8, W - 40, y - 8)
    totals = [("Nettó összesen", f["net_total_huf"]), (f"ÁFA {f['vat_rate']}%", f["vat_huf"]), ("Bruttó összesen", f["gross_total_huf"])]
    if layout == "inv_c":
        totals = [("Nettó", f["net_total_huf"]), (f"ÁFA ({f['vat_rate']}%)", f["vat_huf"]), ("Fizetendő", f["gross_total_huf"])]
    for i, (label, val) in enumerate(totals):
        y -= 18
        c.setFont(head if i == 2 else body, 10 if i == 2 else 9)
        c.drawString(W - 260, y, label)
        c.drawRightString(W - 40, y, f"{huf(val)} Ft")
    c.setFont(body, 8)
    c.setFillColor(GREY)
    c.drawString(40, 60, "Fizetési mód: átutalás · Fizetési határidő: 8 nap · A számla a 2007. évi CXXVII. törvény szerint készült.")


def accident_statement(c: Canvas, cl: Claim, f: dict, layout: str) -> None:
    t = L[cl.lang]
    c.setFillColor(INK)
    c.setFont("SansB", 14)
    c.drawCentredString(W / 2, H - 55, t["eas"])
    c.setFont("Sans", 9)
    c.drawString(40, H - 85, f"1. {t['date']}: {f['date']}    {t['time']}: {f['time']}")
    c.drawString(40, H - 100, f"2. {t['loc']}: {f['location']}")
    c.drawString(40, H - 115, f"3. {t['inj']}: {t['yes'] if f['injuries'] else t['no']}    4. {t['wit']}: {t['yes'] if f['witnesses'] else t['no']}")
    for col, key, x in [("A", "vehicle_a", 40), ("B", "vehicle_b", W / 2 + 10)]:
        v = f[key]
        c.setFillColor(HexColor("#dbe8f3") if col == "A" else HexColor("#f6edd5"))
        c.rect(x, H - 330, W / 2 - 50, 190, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont("SansB", 11)
        c.drawString(x + 8, H - 160, f"{t['veh']} {col}")
        c.setFont("Sans", 9)
        c.drawString(x + 8, H - 180, f"{t['plate']}: {v['plate']}")
        c.drawString(x + 8, H - 195, f"{t['insurer']}: {v['insurer']}")
        c.drawString(x + 8, H - 210, f"{t['driver']}: {v['driver_name']}")
        c.setFont("SansB", 8.5)
        c.drawString(x + 8, H - 232, t["circ"])
        marked = {s.split(": ", 1)[1] for s in f[f"circumstances_{col.lower()}"]}
        c.setFont("Sans", 8)
        for i, circ in enumerate(CIRCUMSTANCES):
            yy = H - 246 - i * 10
            c.rect(x + 8, yy - 1, 6, 6)
            if circ in marked:
                c.drawString(x + 8.6, yy, "X")
            c.drawString(x + 18, yy, circ)
    c.setFont("Sans", 8)
    c.drawString(40, H - 350, "Az A és B jármű vezetője a bejelentőt közösen kitöltötte és aláírta.")


RENDER = {"claim_form": claim_form, "repair_invoice": repair_invoice, "accident_statement": accident_statement}


def scan(pdf: Path, out: Path, rng: random.Random) -> None:
    """Rasterise and degrade like an office scanner: slight rotation, blur, noise, grey paper."""
    page = pdfium.PdfDocument(str(pdf))[0]
    img = page.render(scale=200 / 72).to_pil().convert("L")
    img = img.rotate(rng.uniform(-1.5, 1.5), expand=True, fillcolor=255, resample=Image.Resampling.BICUBIC)
    img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.2, 0.6)))
    noise = Image.effect_noise(img.size, rng.uniform(8, 18))
    img = Image.blend(img, noise, 0.08).point(lambda v: min(255, int(v * 0.93 + 8)))
    img.save(out, optimize=True)


def render_all(claims: list[Claim], out_dir: Path, scan_share: float = 0.3, seed: int = 11) -> Path:
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / "manifest.jsonl"
    with manifest.open("w", encoding="utf-8") as m:
        for cl in claims:
            for i, d in enumerate(cl.documents):
                doc_id = f"{cl.id}-{i + 1}"
                pdf = out_dir / f"{doc_id}.pdf"
                c = Canvas(str(pdf), pagesize=A4)
                RENDER[d["type"]](c, cl, d["fields"], d["layout"])
                c.showPage()
                c.save()
                file = pdf.name
                if rng.random() < scan_share:
                    scan(pdf, out_dir / f"{doc_id}.png", rng)
                    pdf.unlink()
                    file = f"{doc_id}.png"
                m.write(json.dumps({"doc_id": doc_id, "claim_id": cl.id, "type": d["type"], "layout": d["layout"], "lang": cl.lang,
                                    "file": file, "fields": d["fields"]}, ensure_ascii=False) + "\n")
    return manifest
