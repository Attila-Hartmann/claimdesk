"""Synthetic motor-insurance claims for the fictional Kékhíd Biztosító.

Every claim has a policy, a vehicle, a loss event and 2–3 documents (claim form, repair invoice, accident statement).
Ground truth for every document field comes from here, so extraction can be scored exactly. Fraud is planted through a
few realistic signals (fresh policy, night-time loss, a ring of repair shops, inflated invoices, shared bank accounts,
fake tax numbers), and the label is drawn from a logistic model of them, so the classifier has something real to learn.
"""

import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

SURNAMES = ["Nagy", "Kovács", "Tóth", "Szabó", "Horváth", "Varga", "Kiss", "Molnár", "Németh", "Farkas", "Balogh", "Papp",
            "Takács", "Juhász", "Lakatos", "Mészáros", "Oláh", "Simon", "Rácz", "Fekete", "Szűcs", "Hegedűs", "Pintér", "Győri"]
GIVEN = ["László", "István", "József", "János", "Zoltán", "Sándor", "Gábor", "Ferenc", "Péter", "Tamás", "Bence", "Dávid",
         "Mária", "Erzsébet", "Katalin", "Éva", "Ilona", "Anna", "Zsuzsanna", "Judit", "Ágnes", "Andrea", "Réka", "Eszter"]
CITIES = [("Budapest", "1134"), ("Budapest", "1117"), ("Budapest", "1043"), ("Debrecen", "4024"), ("Szeged", "6720"),
          ("Miskolc", "3525"), ("Pécs", "7621"), ("Győr", "9021"), ("Nyíregyháza", "4400"), ("Kecskemét", "6000"),
          ("Székesfehérvár", "8000"), ("Szombathely", "9700"), ("Eger", "3300"), ("Veszprém", "8200")]
STREETS = ["Kossuth Lajos utca", "Petőfi Sándor utca", "Rákóczi út", "Ady Endre utca", "Fő utca", "Széchenyi tér",
           "Dózsa György út", "Bajcsy-Zsilinszky út", "Arany János utca", "Jókai Mór utca", "Váci út", "Béke tér"]
VEHICLES = [("Suzuki", "Vitara", 7_500_000), ("Škoda", "Octavia", 9_200_000), ("Opel", "Astra", 6_800_000),
            ("Toyota", "Corolla", 9_900_000), ("Volkswagen", "Golf", 9_400_000), ("Ford", "Focus", 7_100_000),
            ("Dacia", "Duster", 6_300_000), ("Renault", "Clio", 5_600_000), ("Kia", "Ceed", 7_800_000),
            ("Hyundai", "i30", 7_600_000), ("BMW", "320d", 16_500_000), ("Mercedes-Benz", "C 200", 18_900_000)]
OTHER_INSURERS = ["Alfa Biztosító", "Delta Biztosító", "Orion Biztosító", "Kékhíd Biztosító", "Hármashalom Biztosító"]

# (name, city, honest?) – the last three form the fraud ring.
SHOPS = [("Autó-Szerviz Kovács Kft.", "Budapest"), ("Duna Karosszéria Bt.", "Budapest"), ("Tisztás Autójavító Kft.", "Debrecen"),
         ("Alföld Car Service Kft.", "Szeged"), ("Mecsek Autóház Zrt.", "Pécs"), ("Rába Szerviz Kft.", "Győr"),
         ("Gyors-Fix Karosszéria Kft.", "Budapest"), ("Profi Lakatos Bt.", "Miskolc"), ("Villám Javító Kft.", "Budapest")]
RING = {"Gyors-Fix Karosszéria Kft.", "Profi Lakatos Bt.", "Villám Javító Kft."}

PARTS = [("Első lökhárító", 68_000, 185_000), ("Hátsó lökhárító", 62_000, 170_000), ("Fényszóró, bal", 45_000, 240_000),
         ("Fényszóró, jobb", 45_000, 240_000), ("Motorháztető", 90_000, 260_000), ("Sárvédő, bal első", 38_000, 120_000),
         ("Ajtó, jobb első", 110_000, 320_000), ("Visszapillantó tükör", 18_000, 75_000), ("Hűtőrács", 22_000, 85_000),
         ("Csomagtérajtó", 120_000, 340_000), ("Szélvédő", 70_000, 210_000)]
LABOUR = [("Karosszériamunka", 14_000, 22_000), ("Fényezés", 16_000, 26_000), ("Szerelési munkadíj", 12_000, 19_000)]

LOSS_KINDS = {
    "rear_end": ("Hátulról nekem jött egy másik autó a {place} közelében, a piros lámpánál álltam.",
                 ["A: álló helyzetben volt"], ["B: hátulról ütközött"]),
    "lane_change": ("Sávváltás közben egy autó belém jött a {place} közelében.",
                    ["A: egyenesen haladt"], ["B: sávot váltott"]),
    "parking": ("Parkolás közben egy oszlopnak ütköztem a {place} melletti parkolóban.", ["A: parkolóhelyről kiállt"], []),
    "hail": ("Jégeső verte meg a parkoló autót a {place} közelében.", [], []),
    "deer": ("Vadbaleset: egy őz ugrott az autó elé a {place} és a szomszéd település között.", [], []),
}

LOSS_EN = {
    "rear_end": "Another car hit me from behind near {place} while I was waiting at a red light.",
    "lane_change": "A car changing lanes hit my car near {place}.",
    "parking": "I hit a pillar while parking in the car park next to {place}.",
    "hail": "Hail damaged the parked car near {place}.",
    "deer": "Wildlife accident: a deer jumped in front of the car between {place} and the next village.",
}


def tax_check_digit(first7: str) -> int:
    """Hungarian tax number (adószám) check digit over the first 7 digits of the 8-digit core."""
    s = sum(int(d) * w for d, w in zip(first7, (9, 7, 3, 1, 9, 7, 3), strict=True))
    return (10 - s % 10) % 10


def tax_number(rng: random.Random, valid: bool = True) -> str:
    first7 = f"{rng.randint(1_000_000, 9_999_999)}"
    check = tax_check_digit(first7)
    if not valid:
        check = (check + rng.randint(1, 9)) % 10
    return f"{first7}{check}-2-{rng.choice(['41', '42', '43', '44', '13', '09', '06', '02'])}"


def iban(rng: random.Random) -> str:
    """Valid Hungarian IBAN (mod-97 check digits) over a random 24-digit account number."""
    bban = "".join(str(rng.randint(0, 9)) for _ in range(24))
    return f"HU{98 - int(bban + '173000') % 97:02d}{bban}"  # H=17, U=30


def plate(rng: random.Random) -> str:
    letters = "ABCDEFGHIJKLMNOPRSTUVWXZ"
    if rng.random() < 0.6:
        return f"A{rng.choice('ABCDEFGHIJ')}{rng.choice(letters)}{rng.choice(letters)}-{rng.randint(100, 999)}"
    return f"{''.join(rng.choice(letters) for _ in range(3))}-{rng.randint(100, 999)}"


@dataclass
class Claim:
    id: str
    lang: str
    policy_number: str
    policy_start: date
    claimant: str
    address: str
    phone: str
    email: str
    payout_iban: str
    make: str
    model: str
    vehicle_value_huf: int
    plate: str
    loss_kind: str
    loss_at: datetime
    loss_place: str
    description: str
    estimated_huf: int
    reported_at: date
    shop: str
    shop_city: str
    prior_claims: int
    fraud: bool
    signals: dict[str, float]
    documents: list[dict] = field(default_factory=list)  # {"type", "fields" (ground truth), "layout"}


def _person(rng: random.Random) -> str:
    return f"{rng.choice(SURNAMES)} {rng.choice(GIVEN)}"


def _invoice(rng: random.Random, c: Claim, inflate: float, fake_tax: bool) -> dict:
    lines = []
    for name, lo, hi in rng.sample(PARTS, rng.randint(1, 3)):
        lines.append({"description": name, "quantity": 1, "unit_price_huf": round(rng.randint(lo, hi) * inflate, -2)})
    for name, lo, hi in rng.sample(LABOUR, rng.randint(1, 2)):
        lines.append({"description": f"{name} (óra)", "quantity": rng.randint(2, 9), "unit_price_huf": round(rng.randint(lo, hi), -2)})
    for li in lines:
        li["net_huf"] = int(li["quantity"] * li["unit_price_huf"])
        li["unit_price_huf"] = int(li["unit_price_huf"])
    net = sum(li["net_huf"] for li in lines)
    vat = round(net * 0.27)
    issue = c.loss_at.date() + timedelta(days=rng.randint(4, 25))
    return {
        "seller_name": c.shop, "seller_tax_number": tax_number(rng, valid=not fake_tax),
        "invoice_number": f"{rng.choice(['SZ', 'KSZ', 'E'])}-{issue.year}/{rng.randint(100, 9999):04d}",
        "issue_date": issue.isoformat(), "fulfilment_date": (issue - timedelta(days=rng.randint(0, 3))).isoformat(),
        "buyer_name": c.claimant, "plate": c.plate, "line_items": lines,
        "net_total_huf": net, "vat_rate": 27, "vat_huf": vat, "gross_total_huf": net + vat,
    }


def generate(n: int, seed: int = 7) -> list[Claim]:
    rng = random.Random(seed)
    shared_ibans = [iban(rng) for _ in range(4)]  # accounts reused across unrelated "claimants": a classic ring signal
    claims = []
    for i in range(n):
        city, zipc = rng.choice(CITIES)
        make, model, value = rng.choice(VEHICLES)
        value = int(value * rng.uniform(0.45, 1.0))
        shop, shop_city = rng.choices(SHOPS, weights=[1 if s[0] not in RING else 0.35 for s in SHOPS])[0]
        in_ring = shop in RING
        policy_start = date(2026, 1, 1) + timedelta(days=rng.randint(-900, 220))
        fresh = rng.random() < (0.35 if in_ring else 0.06)
        loss_day = policy_start + timedelta(days=rng.randint(3, 28) if fresh else rng.randint(30, 600))
        loss_day = min(loss_day, date(2026, 10, 25))
        night = rng.random() < (0.45 if in_ring else 0.12)
        hour = rng.choice([0, 1, 2, 3, 23]) if night else rng.randint(7, 20)
        loss_at = datetime(loss_day.year, loss_day.month, loss_day.day, hour, rng.choice([0, 10, 20, 30, 40, 50]))
        kind = rng.choice(list(LOSS_KINDS))
        place = f"{city}, {rng.choice(STREETS)}"
        inflate = rng.uniform(1.4, 2.2) if in_ring and rng.random() < 0.7 else rng.uniform(0.95, 1.1)
        fake_tax = in_ring and rng.random() < 0.25
        shared = in_ring and rng.random() < 0.3
        prior = rng.choices([0, 1, 2, 3], weights=[70, 20, 7, 3] if not in_ring else [40, 30, 20, 10])[0]
        name = _person(rng)
        lang = "hu" if rng.random() < 0.85 else "en"
        c = Claim(
            id=f"KH-{2026}-{10_000 + i}", lang=lang,
            policy_number=f"KH-CASCO-{policy_start.year}-{rng.randint(1, 999_999):06d}", policy_start=policy_start,
            claimant=name, address=f"{zipc} {city}, {rng.choice(STREETS)} {rng.randint(1, 120)}.",
            phone=f"+36 {rng.choice(['20', '30', '70'])} {rng.randint(100, 999)} {rng.randint(1000, 9999)}",
            email=f"{name.split()[1].lower()}.{name.split()[0].lower()}{rng.randint(1, 99)}@{rng.choice(['gmail.com', 'freemail.hu', 'citromail.hu'])}"  # noqa: E501
            .translate(str.maketrans("áéíóöőúüű", "aeiooouuu")),
            payout_iban=rng.choice(shared_ibans) if shared else iban(rng), make=make, model=model, vehicle_value_huf=value,
            plate=plate(rng), loss_kind=kind, loss_at=loss_at, loss_place=place,
            description=(LOSS_KINDS[kind][0] if lang == "hu" else LOSS_EN[kind]).format(place=place.split(",")[0]), estimated_huf=0,
            reported_at=loss_day + timedelta(days=rng.randint(0, 6)), shop=shop, shop_city=shop_city, prior_claims=prior,
            fraud=False, signals={},
        )
        inv = _invoice(rng, c, inflate, fake_tax)
        c.estimated_huf = int(round(inv["gross_total_huf"] / inflate * rng.uniform(0.9, 1.1), -3))
        c.signals = {
            "days_since_policy_start": (loss_day - policy_start).days, "night_time": float(night), "shop_in_ring": float(in_ring),
            "invoice_vs_estimate": inv["gross_total_huf"] / max(c.estimated_huf, 1), "claim_vs_vehicle_value": inv["gross_total_huf"] / value,
            "prior_claims": prior, "invalid_tax_number": float(fake_tax), "shared_iban": float(shared),
        }
        logit = (-4.6 + 1.6 * (c.signals["days_since_policy_start"] < 30) + 0.9 * night + 1.1 * in_ring
                 + 1.4 * (c.signals["invoice_vs_estimate"] > 1.3) + 0.5 * prior + 2.5 * fake_tax + 2.0 * shared)
        c.fraud = rng.random() < 1 / (1 + math.exp(-logit))

        c.documents.append({"type": "claim_form", "layout": rng.choice(["form_a", "form_b"]), "fields": {
            "policy_number": c.policy_number, "claimant_name": c.claimant, "address": c.address, "phone": c.phone, "email": c.email,
            "plate": c.plate, "vehicle": f"{make} {model}", "loss_datetime": loss_at.isoformat(timespec="minutes"),
            "loss_location": place, "description": c.description, "estimated_amount_huf": c.estimated_huf,
            "payout_iban": c.payout_iban, "signed_date": c.reported_at.isoformat()}})
        c.documents.append({"type": "repair_invoice", "layout": rng.choice(["inv_a", "inv_b", "inv_c"]), "fields": inv})
        if LOSS_KINDS[kind][2]:  # another vehicle was involved
            other = _person(rng)
            c.documents.append({"type": "accident_statement", "layout": "eas", "fields": {
                "date": loss_at.date().isoformat(), "time": loss_at.strftime("%H:%M"), "location": place,
                "vehicle_a": {"plate": c.plate, "insurer": "Kékhíd Biztosító", "driver_name": c.claimant},
                "vehicle_b": {"plate": plate(rng), "insurer": rng.choice(OTHER_INSURERS), "driver_name": other},
                "circumstances_a": LOSS_KINDS[kind][1], "circumstances_b": LOSS_KINDS[kind][2],
                "injuries": rng.random() < 0.08, "witnesses": rng.random() < 0.3}})
        claims.append(c)
    return claims


if __name__ == "__main__":
    cs = generate(600)
    assert all(tax_check_digit(t[:7]) == int(t[7]) for c in cs for d in c.documents if d["type"] == "repair_invoice"
               and not c.signals["invalid_tax_number"] for t in [d["fields"]["seller_tax_number"]])
    print(len(cs), "claims,", sum(len(c.documents) for c in cs), "documents,", f"{sum(c.fraud for c in cs) / len(cs):.1%} fraud")
