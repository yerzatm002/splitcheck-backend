import unittest
from decimal import Decimal

from app.services.receipt_parser import _parse_spatial_items


def row(text, confidence=0.95):
    # Minimal synthetic visual row. A single token is enough for parser regression tests.
    return {
        "text": text,
        "confidence": confidence,
        "tokens": [
            {
                "text": text,
                "x1": 0.0,
                "x2": 500.0,
            }
        ],
    }


class WeightedReceiptParserTest(unittest.TestCase):
    def test_net_weight_line_enriches_next_product(self):
        rows = [
            row("DESCRIZIONE IVA PREZZO(E)"),
            row("LATTE P.SCREMATO UHT 4% 0.84"),
            row("0.580kg LORDO - 0.004kg TARA"),
            row("0.576kg NETTO x EUR 0.98/kg"),
            row("BANANE CAVENDISH 4% 0.56"),
            row("SACCHETTO ORTOFRUTTA 22% 0.01"),
            row("ARTICOLI 14"),
        ]

        items = _parse_spatial_items(rows)
        self.assertEqual([item["name"] for item in items], [
            "LATTE P.SCREMATO UHT",
            "BANANE CAVENDISH",
            "SACCHETTO ORTOFRUTTA",
        ])

        banana = items[1]
        self.assertEqual(banana["quantity"], Decimal("0.576"))
        self.assertEqual(banana["unit"], "kg")
        self.assertEqual(banana["unit_price_cents"], 98)
        self.assertEqual(banana["total_price_cents"], 56)

    def test_weight_metadata_never_becomes_product(self):
        rows = [
            row("DESCRIZIONE IVA PREZZO(E)"),
            row("0.696kg NETTO x EUR 2.79/kg"),
            row("POMODORO GRAPPOLO 4% 1.94"),
            row("ARTICOLI 1"),
        ]
        items = _parse_spatial_items(rows)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "POMODORO GRAPPOLO")
        self.assertEqual(items[0]["quantity"], Decimal("0.696"))
        self.assertEqual(items[0]["unit_price_cents"], 279)
        self.assertEqual(items[0]["total_price_cents"], 194)

    def test_bad_weight_math_does_not_attach_to_unrelated_product(self):
        rows = [
            row("DESCRIZIONE IVA PREZZO(E)"),
            row("0.576kg NETTO x EUR 0.98/kg"),
            row("TONNO NATURALE 10% 1.29"),
            row("ARTICOLI 1"),
        ]
        items = _parse_spatial_items(rows)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "TONNO NATURALE")
        self.assertEqual(items[0]["unit"], "pcs")
        self.assertIsNone(items[0]["unit_price_cents"])
        self.assertEqual(items[0]["total_price_cents"], 129)


if __name__ == "__main__":
    unittest.main()
