"""What we extract per document type. The same models validate LLM output and define the fine-tuning targets."""

from typing import Literal

from pydantic import BaseModel, Field

DocType = Literal["claim_form", "repair_invoice", "accident_statement"]


class ClaimForm(BaseModel):
    policy_number: str
    claimant_name: str
    address: str
    phone: str
    email: str
    plate: str = Field(description="vehicle registration, e.g. AEBC-123 or ABC-123")
    vehicle: str = Field(description="make and model")
    loss_datetime: str = Field(description="ISO 8601, YYYY-MM-DDTHH:MM")
    loss_location: str
    description: str
    estimated_amount_huf: int
    payout_iban: str = Field(description="HU + 26 digits, no spaces")
    signed_date: str = Field(description="YYYY-MM-DD")


class LineItem(BaseModel):
    description: str
    quantity: int
    unit_price_huf: int
    net_huf: int


class RepairInvoice(BaseModel):
    seller_name: str
    seller_tax_number: str = Field(description="Hungarian tax number, 12345678-1-12")
    invoice_number: str
    issue_date: str = Field(description="YYYY-MM-DD")
    fulfilment_date: str = Field(description="YYYY-MM-DD")
    buyer_name: str
    plate: str
    line_items: list[LineItem]
    net_total_huf: int
    vat_rate: int
    vat_huf: int
    gross_total_huf: int


class Vehicle(BaseModel):
    plate: str
    insurer: str
    driver_name: str


class AccidentStatement(BaseModel):
    date: str = Field(description="YYYY-MM-DD")
    time: str = Field(description="HH:MM")
    location: str
    vehicle_a: Vehicle
    vehicle_b: Vehicle
    circumstances_a: list[str] = Field(description='ticked boxes for vehicle A, each prefixed "A: "')
    circumstances_b: list[str] = Field(description='ticked boxes for vehicle B, each prefixed "B: "')
    injuries: bool
    witnesses: bool


SCHEMAS: dict[str, type[BaseModel]] = {"claim_form": ClaimForm, "repair_invoice": RepairInvoice, "accident_statement": AccidentStatement}
