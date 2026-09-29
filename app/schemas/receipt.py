from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field


class ParticipantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    user_id: int | None = None


class ParticipantOut(ParticipantCreate):
    id: int
    model_config = {"from_attributes": True}


class ReceiptCreate(BaseModel):
    store_name: str | None = None
    currency: str = "EUR"
    total_amount_cents: int = 0
    participants: list[ParticipantCreate] = []


class ReceiptItemCreate(BaseModel):
    name: str
    quantity: Decimal = Decimal("1")
    unit: str = "pcs"
    unit_price_cents: int | None = None
    total_price_cents: int
    ocr_confidence: Decimal | None = None


class ReceiptItemUpdate(BaseModel):
    name: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price_cents: int | None = None
    total_price_cents: int | None = None


class ItemSplitOut(BaseModel):
    participant_id: int
    amount_cents: int
    share: Decimal


class ReceiptItemOut(BaseModel):
    id: int
    name: str
    quantity: Decimal
    unit: str
    unit_price_cents: int | None
    total_price_cents: int
    ocr_confidence: Decimal | None
    splits: list[ItemSplitOut] = []

    model_config = {"from_attributes": True}


class ReceiptOut(BaseModel):
    id: int
    store_name: str | None
    receipt_date: datetime | None
    currency: str
    total_amount_cents: int
    ocr_status: str
    created_at: datetime
    participants: list[ParticipantOut] = []
    items: list[ReceiptItemOut] = []

    model_config = {"from_attributes": True}


class SplitRequest(BaseModel):
    participant_ids: list[int] = Field(min_length=1)


class ParticipantSummary(BaseModel):
    participant_id: int
    name: str
    amount_cents: int


class ReceiptSummary(BaseModel):
    receipt_id: int
    receipt_total_cents: int
    allocated_total_cents: int
    difference_cents: int
    participants: list[ParticipantSummary]


class OCRTextRequest(BaseModel):
    raw_text: str = Field(min_length=1, max_length=50000)
    confidence: float | None = Field(default=None, ge=0, le=1)


class OCRItem(BaseModel):
    name: str
    quantity: Decimal = Decimal("1")
    unit: str = "pcs"
    unit_price_cents: int | None = None
    total_price_cents: int
    confidence: Decimal | None = None


class OCRResponse(BaseModel):
    store_name: str | None = None
    currency: str = "EUR"
    total_cents: int = 0
    items: list[OCRItem]
    raw_text: str
