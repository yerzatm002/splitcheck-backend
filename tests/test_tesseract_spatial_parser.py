from app.services.receipt_parser import parse_italian_receipt


def tok(text, x0, y0, x1, y1, conf=0.9):
    return {
        'text': text,
        'confidence': conf,
        'box': [[x0,y0],[x1,y0],[x1,y1],[x0,y1]],
    }


def test_tesseract_columns_drop_bleed_through_and_footer_items():
    tokens = [
        tok('DESCRIZIONE', 100, 100, 240, 125),
        tok('IVA', 520, 100, 555, 125),
        tok('PREZZO(€)', 600, 100, 720, 125),
        # Product 1 with garbage outside the real description column
        tok('i', 55, 150, 65, 170, 0.2), tok('VA', 72, 150, 92, 170, 0.25),
        tok('SNACK', 110, 150, 180, 170), tok('LATTE', 190, 150, 250, 170),
        tok('NN', 430, 150, 455, 170, 0.2), tok('10%', 525, 150, 560, 170), tok('1.19', 650, 150, 700, 170),
        # Product 2
        tok('PATATE', 110, 185, 185, 205), tok('TUTTI', 195, 185, 250, 205), tok('GLI', 260, 185, 295, 205), tok('USI', 305, 185, 340, 205),
        tok('4%', 525, 185, 550, 205), tok('2.49', 650, 185, 700, 205),
        tok('ARTICOLI', 110, 225, 200, 245), tok('2', 260, 225, 275, 245),
        tok('TOTALE', 110, 270, 200, 295), tok('COMPLESSIVO', 210, 270, 350, 295), tok('€', 365, 270, 375, 295), tok('3.68', 650, 270, 700, 295),
        # Footer line that must never become an item
        tok('DI', 110, 310, 130, 330), tok('CUI', 140, 310, 175, 330), tok('IVA', 185, 310, 220, 330), tok('0.30', 650, 310, 700, 330),
    ]
    parsed = parse_italian_receipt(tokens)
    assert parsed['total_cents'] == 368
    assert [i['name'] for i in parsed['items']] == ['SNACK LATTE', 'PATATE TUTTI GLI USI']
    assert sum(i['total_price_cents'] for i in parsed['items']) == 368
