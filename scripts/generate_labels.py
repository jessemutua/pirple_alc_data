# scripts/generate_labels.py
"""
Generate scannable test labels from the serial ledger.

    pip install ppf-datamatrix segno

    python scripts/generate_labels.py                     # 4 of each case
    python scripts/generate_labels.py --count 8 --qr
    python scripts/generate_labels.py --case fabricated --count 20

Writes SVG labels, a printable sheet, and a manifest saying what each label
should return when scanned.

Cases:
  genuine     real barcode, issued serial, never scanned  -> verified
  fabricated  real barcode, serial never issued           -> suspicious
  clone       same issued serial printed twice            -> second suspicious
  unknown     barcode belonging to no manufacturer        -> suspicious

Note: a production GS1 DataMatrix carries an FNC1 codeword in first position
to mark it as a GS1 message. This encoder does not emit one. The app's parser
reads the payload either way, so these are valid for testing, but real
manufacturer printing would use a GS1 certified encoder.
"""
import argparse
import csv
import random
import re
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import exists, select  # noqa: E402

from core.database import SessionLocal  # noqa: E402
from drinks.scan_models import ScanEvent  # noqa: E402
from products.models import Product, ProductSerial  # noqa: E402

try:
    from ppf.datamatrix import DataMatrix
except ImportError:
    print("missing dependency, run: pip install ppf-datamatrix segno")
    raise SystemExit(2)

SERIAL_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SERIAL_LENGTH = 10
DEFAULT_COUNT = 4
LABEL_PX = 180

CASES = ("genuine", "fabricated", "clone", "unknown")

EXPECTED = {
    "genuine": "verified",
    "fabricated": "suspicious",
    "clone": "verified, then suspicious on the second scan",
    "unknown": "suspicious",
}


def gs1_payload(gtin14: str, serial: str) -> str:
    """(01) product, (21) this bottle. The whole basis of verification."""
    return f"01{gtin14}21{serial}"


def check_digit(body: str) -> str:
    total = sum(
        (3 if i % 2 == 0 else 1) * int(d) for i, d in enumerate(reversed(body))
    )
    return str((10 - total % 10) % 10)


def unregistered_gtin(index: int) -> str:
    """A structurally valid GTIN in a range no manufacturer is seeded into."""
    body = "999" + f"{index:09d}"
    return "0" + body + check_digit(body)


def random_serial() -> str:
    return "".join(secrets.choice(SERIAL_ALPHABET) for _ in range(SERIAL_LENGTH))


def scale_svg(svg: str, size_px: int) -> str:
    """
    The encoder emits a module-sized SVG with no viewBox, so it cannot scale.
    Add one and set a print friendly size.
    """
    match = re.search(r'height="(\d+)px" width="(\d+)px"', svg)
    if not match:
        return svg

    height, width = match.group(1), match.group(2)
    return svg.replace(
        match.group(0),
        f'height="{size_px}px" width="{size_px}px" '
        f'viewBox="0 0 {width} {height}" shape-rendering="crispEdges"',
    )


def write_label(out_dir: Path, name: str, payload: str, qr: bool) -> dict:
    svg = scale_svg(DataMatrix(payload).svg(), LABEL_PX)
    dm_path = out_dir / f"{name}.svg"
    dm_path.write_text(svg, encoding="utf-8")

    files = {"datamatrix": dm_path.name}

    if qr:
        import segno

        qr_path = out_dir / f"{name}-qr.svg"
        segno.make(payload, error="m").save(
            str(qr_path), scale=6, border=2, kind="svg"
        )
        files["qr"] = qr_path.name

    return files


def genuine_serials(db, limit: int) -> list[tuple[str, str, str]]:
    """Issued serials with no scan history, so the reuse rules stay dormant."""
    rows = db.execute(
        select(ProductSerial.gtin14, ProductSerial.serial, Product.product_name)
        .join(Product, Product.gtin14 == ProductSerial.gtin14)
        .where(
            ProductSerial.status == "issued",
            ~exists().where(
                ScanEvent.serial == ProductSerial.serial,
                ScanEvent.gtin == ProductSerial.gtin14,
            ),
        )
        .limit(limit)
    ).all()
    return [(r[0], r[1], r[2]) for r in rows]


def real_products(db, limit: int) -> list[tuple[str, str]]:
    rows = db.execute(
        select(Product.gtin14, Product.product_name)
        .where(Product.is_active.is_(True))
        .limit(limit)
    ).all()
    return [(r[0], r[1]) for r in rows]


def build(db, case: str, count: int, out_dir: Path, qr: bool) -> list[dict]:
    labels: list[dict] = []

    if case == "genuine":
        for gtin, serial, product in genuine_serials(db, count):
            name = f"genuine-{serial}"
            files = write_label(out_dir, name, gs1_payload(gtin, serial), qr)
            labels.append(
                {
                    "case": "genuine",
                    "product": product,
                    "gtin": gtin,
                    "serial": serial,
                    "expected": EXPECTED["genuine"],
                    **files,
                }
            )

    elif case == "fabricated":
        products = real_products(db, max(count, 1))
        for index in range(count):
            gtin, product = products[index % len(products)]
            serial = random_serial()
            name = f"fabricated-{serial}"
            files = write_label(out_dir, name, gs1_payload(gtin, serial), qr)
            labels.append(
                {
                    "case": "fabricated",
                    "product": product,
                    "gtin": gtin,
                    "serial": serial,
                    "expected": EXPECTED["fabricated"],
                    **files,
                }
            )

    elif case == "clone":
        # Pairs: the same issued serial printed twice.
        pairs = max(count // 2, 1)
        for gtin, serial, product in genuine_serials(db, pairs):
            for copy in ("a", "b"):
                name = f"clone-{serial}-{copy}"
                files = write_label(out_dir, name, gs1_payload(gtin, serial), qr)
                labels.append(
                    {
                        "case": "clone",
                        "product": product,
                        "gtin": gtin,
                        "serial": f"{serial} (copy {copy})",
                        "expected": EXPECTED["clone"],
                        **files,
                    }
                )

    elif case == "unknown":
        for index in range(count):
            gtin = unregistered_gtin(index + 1)
            serial = random_serial()
            name = f"unknown-{serial}"
            files = write_label(out_dir, name, gs1_payload(gtin, serial), qr)
            labels.append(
                {
                    "case": "unknown",
                    "product": "not in any catalogue",
                    "gtin": gtin,
                    "serial": serial,
                    "expected": EXPECTED["unknown"],
                    **files,
                }
            )

    return labels


def write_sheet(out_dir: Path, labels: list[dict], qr: bool) -> Path:
    cards = []
    for label in labels:
        image = label.get("qr") if qr and label.get("qr") else label["datamatrix"]
        cards.append(
            f"""
      <figure class="label">
        <img src="{image}" alt="{label['case']} label" />
        <figcaption>
          <strong>{label['case']}</strong>
          <span>{label['product']}</span>
          <code>{label['gtin']}</code>
          <code>{label['serial']}</code>
          <em>expects: {label['expected']}</em>
        </figcaption>
      </figure>"""
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Limi test labels</title>
<style>
  body {{ font: 13px system-ui, sans-serif; margin: 24px; color: #111; }}
  h1 {{ font-size: 18px; margin: 0 0 4px; }}
  p.note {{ color: #555; margin: 0 0 24px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 20px; }}
  .label {{ margin: 0; border: 1px solid #ddd; border-radius: 8px; padding: 14px; text-align: center; break-inside: avoid; }}
  .label img {{ width: 170px; height: 170px; }}
  figcaption {{ display: grid; gap: 2px; margin-top: 10px; }}
  figcaption strong {{ text-transform: uppercase; letter-spacing: .04em; font-size: 11px; }}
  figcaption span {{ font-size: 12px; }}
  figcaption code {{ font-size: 11px; color: #444; }}
  figcaption em {{ font-size: 11px; color: #666; }}
  @media print {{ .label {{ border-color: #999; }} }}
</style>
</head>
<body>
  <h1>Limi test labels</h1>
  <p class="note">
    {len(labels)} labels. Scan with the Limi app and compare against the expected
    result printed under each code. Print at 100% scale, do not fit to page.
  </p>
  <div class="grid">{''.join(cards)}
  </div>
</body>
</html>
"""

    path = out_dir / "sheet.html"
    path.write_text(html, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate GS1 test labels.")
    parser.add_argument("--case", choices=CASES + ("all",), default="all")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--qr", action="store_true", help="also emit QR versions")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "labels")
    args = parser.parse_args()

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = CASES if args.case == "all" else (args.case,)

    db = SessionLocal()
    try:
        labels: list[dict] = []
        for case in cases:
            produced = build(db, case, args.count, out_dir, args.qr)
            print(f"{case:12} {len(produced)} labels")
            labels.extend(produced)
    finally:
        db.close()

    if not labels:
        print("nothing generated, is the catalogue seeded?")
        return 1

    manifest = out_dir / "manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["case", "product", "gtin", "serial", "expected", "datamatrix", "qr"],
        )
        writer.writeheader()
        for label in labels:
            writer.writerow({key: label.get(key, "") for key in writer.fieldnames})

    sheet = write_sheet(out_dir, labels, args.qr)

    print(f"\n{len(labels)} labels in {out_dir}")
    print(f"sheet    : {sheet}")
    print(f"manifest : {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(0 if main() == 0 else 1)