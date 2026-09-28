from decimal import Decimal
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import ItemSplit, Participant, Receipt, ReceiptItem, User
from app.schemas.receipt import (
    OCRResponse,
    ParticipantCreate,
    ParticipantOut,
    ParticipantSummary,
    ReceiptCreate,
    ReceiptItemCreate,
    ReceiptItemOut,
    ReceiptItemUpdate,
    ReceiptOut,
    ReceiptSummary,
    SplitRequest,
)
from app.services.ocr_service import recognize_receipt
from app.services.split_service import split_cents_evenly

router = APIRouter(prefix="/receipts", tags=["receipts"])


def _receipt_query():
    return select(Receipt).options(
        selectinload(Receipt.participants),
        selectinload(Receipt.items).selectinload(ReceiptItem.splits),
    )


@router.post("", response_model=ReceiptOut)
def create_receipt(payload: ReceiptCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    receipt = Receipt(
        created_by=current_user.id,
        store_name=payload.store_name,
        currency=payload.currency.upper(),
        total_amount_cents=payload.total_amount_cents,
    )
    db.add(receipt)
    db.flush()
    for p in payload.participants:
        db.add(Participant(receipt_id=receipt.id, name=p.name.strip(), user_id=p.user_id))
    db.commit()
    return db.scalar(_receipt_query().where(Receipt.id == receipt.id))


@router.get("", response_model=list[ReceiptOut])
def list_receipts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    stmt = _receipt_query().where(Receipt.created_by == current_user.id).order_by(Receipt.created_at.desc())
    return db.scalars(stmt).unique().all()


@router.get("/{receipt_id}", response_model=ReceiptOut)
def get_receipt(receipt_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    receipt = db.scalar(_receipt_query().where(Receipt.id == receipt_id, Receipt.created_by == current_user.id))
    if not receipt:
        raise HTTPException(404, "Receipt not found")
    return receipt


@router.delete("/{receipt_id}")
def delete_receipt(receipt_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    receipt = db.scalar(select(Receipt).where(Receipt.id == receipt_id, Receipt.created_by == current_user.id))
    if not receipt:
        raise HTTPException(404, "Receipt not found")
    db.delete(receipt)
    db.commit()
    return {"ok": True}


@router.post("/{receipt_id}/participants", response_model=ParticipantOut)
def add_participant(receipt_id: int, payload: ParticipantCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    receipt = db.scalar(select(Receipt).where(Receipt.id == receipt_id, Receipt.created_by == current_user.id))
    if not receipt:
        raise HTTPException(404, "Receipt not found")
    participant = Participant(receipt_id=receipt_id, name=payload.name.strip(), user_id=payload.user_id)
    db.add(participant)
    db.commit()
    db.refresh(participant)
    return participant


@router.delete("/{receipt_id}/participants/{participant_id}")
def remove_participant(receipt_id: int, participant_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    participant = db.scalar(
        select(Participant)
        .join(Receipt, Receipt.id == Participant.receipt_id)
        .where(Participant.id == participant_id, Participant.receipt_id == receipt_id, Receipt.created_by == current_user.id)
    )
    if not participant:
        raise HTTPException(404, "Participant not found")
    db.delete(participant)
    db.commit()
    return {"ok": True}


@router.post("/{receipt_id}/items", response_model=ReceiptItemOut)
def add_item(receipt_id: int, payload: ReceiptItemCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    receipt = db.scalar(select(Receipt).where(Receipt.id == receipt_id, Receipt.created_by == current_user.id))
    if not receipt:
        raise HTTPException(404, "Receipt not found")
    item = ReceiptItem(receipt_id=receipt_id, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{receipt_id}/items/{item_id}", response_model=ReceiptItemOut)
def update_item(receipt_id: int, item_id: int, payload: ReceiptItemUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.scalar(
        select(ReceiptItem).join(Receipt).where(
            ReceiptItem.id == item_id,
            ReceiptItem.receipt_id == receipt_id,
            Receipt.created_by == current_user.id,
        )
    )
    if not item:
        raise HTTPException(404, "Item not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{receipt_id}/items/{item_id}")
def remove_item(receipt_id: int, item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.scalar(
        select(ReceiptItem).join(Receipt).where(
            ReceiptItem.id == item_id,
            ReceiptItem.receipt_id == receipt_id,
            Receipt.created_by == current_user.id,
        )
    )
    if not item:
        raise HTTPException(404, "Item not found")
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.put("/{receipt_id}/items/{item_id}/split", response_model=list[dict])
def split_item(receipt_id: int, item_id: int, payload: SplitRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.scalar(
        select(ReceiptItem).join(Receipt).where(
            ReceiptItem.id == item_id,
            ReceiptItem.receipt_id == receipt_id,
            Receipt.created_by == current_user.id,
        )
    )
    if not item:
        raise HTTPException(404, "Item not found")

    participants = db.scalars(select(Participant).where(Participant.receipt_id == receipt_id, Participant.id.in_(payload.participant_ids))).all()
    if len({p.id for p in participants}) != len(set(payload.participant_ids)):
        raise HTTPException(400, "One or more participants do not belong to this receipt")

    db.execute(delete(ItemSplit).where(ItemSplit.receipt_item_id == item_id))
    calculated = split_cents_evenly(item.total_price_cents, payload.participant_ids)
    count = len(calculated)
    for participant_id, amount in calculated:
        db.add(ItemSplit(
            receipt_item_id=item_id,
            participant_id=participant_id,
            amount_cents=amount,
            share=Decimal(1) / Decimal(count),
        ))
    db.commit()
    return [{"participant_id": p, "amount_cents": a} for p, a in calculated]


@router.get("/{receipt_id}/summary", response_model=ReceiptSummary)
def receipt_summary(receipt_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    receipt = db.scalar(_receipt_query().where(Receipt.id == receipt_id, Receipt.created_by == current_user.id))
    if not receipt:
        raise HTTPException(404, "Receipt not found")

    totals = {p.id: 0 for p in receipt.participants}
    for item in receipt.items:
        for split in item.splits:
            totals[split.participant_id] = totals.get(split.participant_id, 0) + split.amount_cents

    allocated = sum(totals.values())
    participants = [
        ParticipantSummary(participant_id=p.id, name=p.name, amount_cents=totals.get(p.id, 0))
        for p in receipt.participants
    ]
    return ReceiptSummary(
        receipt_id=receipt.id,
        receipt_total_cents=receipt.total_amount_cents,
        allocated_total_cents=allocated,
        difference_cents=receipt.total_amount_cents - allocated,
        participants=participants,
    )


@router.post("/{receipt_id}/ocr", response_model=OCRResponse)
async def ocr_receipt(receipt_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    receipt = db.scalar(select(Receipt).where(Receipt.id == receipt_id, Receipt.created_by == current_user.id))
    if not receipt:
        raise HTTPException(404, "Receipt not found")
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(400, "Please upload an image")

    data = await file.read()
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(413, "Image is too large (max 12 MB)")

    receipt.ocr_status = "PROCESSING"
    db.commit()

    try:
        # OCR is CPU-bound. Run it outside FastAPI's event loop so health/API requests
        # remain responsive while PaddleOCR works.
        parsed = await run_in_threadpool(recognize_receipt, data)
    except Exception as exc:
        receipt.ocr_status = "FAILED"
        db.commit()
        raise HTTPException(422, f"OCR failed: {exc}")

    receipt.store_name = parsed.get("store_name") or receipt.store_name
    receipt.total_amount_cents = parsed.get("total_cents") or receipt.total_amount_cents
    receipt.raw_ocr_text = parsed.get("raw_text")
    receipt.ocr_status = "DONE"

    # Replace only OCR-created list for MVP. Do OCR before manual editing.
    db.execute(delete(ReceiptItem).where(ReceiptItem.receipt_id == receipt.id))
    for idx, item in enumerate(parsed["items"]):
        db.add(ReceiptItem(
            receipt_id=receipt.id,
            name=item["name"],
            quantity=item["quantity"],
            unit=item["unit"],
            unit_price_cents=item["unit_price_cents"],
            total_price_cents=item["total_price_cents"],
            ocr_confidence=item["confidence"],
            sort_order=idx,
        ))
    db.commit()

    return OCRResponse(
        store_name=parsed.get("store_name"),
        currency="EUR",
        total_cents=parsed.get("total_cents", 0),
        items=[
            {
                "name": x["name"],
                "quantity": x["quantity"],
                "unit": x["unit"],
                "unit_price_cents": x["unit_price_cents"],
                "total_price_cents": x["total_price_cents"],
                "confidence": x["confidence"],
            }
            for x in parsed["items"]
        ],
        raw_text=parsed.get("raw_text", ""),
    )
