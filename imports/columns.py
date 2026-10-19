"""CSV column guide for lead, account, and contact imports."""

import csv
import io

from accounts.models import Account
from core.taxonomy import TAXONOMY

ENTITIES = ("lead", "account", "contact")
POLICIES = ("skip", "update", "create")
OWNER_NOTE = (
    "The person's name as shown in GlideCRM, not the login username. Blank means you."
)


def _keys(list_key):
    return ", ".join(key for key, _label in TAXONOMY[list_key])


def _labeled(pairs):
    return ", ".join(f"{key} ({label})" for key, label in pairs)


def _address_columns():
    return [
        Column(
            "street",
            "Street",
            required=False,
            instructions="Text, up to 200 characters. Leave blank when unknown.",
        ),
        Column(
            "city",
            "City",
            required=False,
            instructions="Text, up to 100 characters.",
        ),
        Column(
            "region",
            "State",
            required=False,
            instructions="State or province, up to 100 characters.",
        ),
        Column(
            "postal_code",
            "Postal code",
            required=False,
            instructions="Text, up to 20 characters.",
        ),
        Column(
            "country",
            "Country",
            required=False,
            instructions="Text, up to 100 characters, such as US.",
        ),
    ]


class Column:
    def __init__(self, key, label, *, required, instructions):
        self.key = key
        self.label = label
        self.required = required
        self.instructions = instructions

    @property
    def requirement(self):
        return "Required" if self.required else "Optional"


def _lead_columns():
    return [
        Column(
            "row_action",
            "Row action",
            required=False,
            instructions=(
                "Leave blank to import the row. Use example to keep a sample "
                "row in the file; example rows are not imported."
            ),
        ),
        Column(
            "external_id",
            "External ID",
            required=False,
            instructions=(
                "Your own id for this lead. Letters, numbers, hyphens, or "
                "underscores, up to 64 characters, and unique. Blank lets "
                "GlideCRM assign one. A repeat import uses this id first."
            ),
        ),
        Column(
            "first_name",
            "First name",
            required=True,
            instructions="Text, up to 80 characters.",
        ),
        Column(
            "last_name",
            "Last name",
            required=True,
            instructions="Text, up to 80 characters.",
        ),
        Column(
            "company_name",
            "Company",
            required=True,
            instructions="Text, up to 200 characters.",
        ),
        Column(
            "source",
            "Source",
            required=True,
            instructions=(
                f"One key: {_keys('LEAD_SOURCE')}. Use the key, not the label."
            ),
        ),
        Column(
            "title",
            "Title",
            required=False,
            instructions="Text, up to 120 characters.",
        ),
        Column(
            "email",
            "Email",
            required=True,
            instructions="name@domain. Matched when external_id is blank.",
        ),
        Column(
            "work_phone",
            "Work phone",
            required=False,
            instructions="Optional. 10 digits, stored as (XXX) XXX-XXXX.",
        ),
        Column(
            "mobile_phone",
            "Mobile phone",
            required=False,
            instructions="Optional. 10 digits, stored as (XXX) XXX-XXXX.",
        ),
        *_address_columns(),
        Column(
            "website_url",
            "Website",
            required=False,
            instructions="example.com or https://example.com.",
        ),
        Column(
            "industry",
            "Industry",
            required=False,
            instructions=(
                f"One key: {_labeled(TAXONOMY['INDUSTRY'])}. "
                "Use the key, not the label."
            ),
        ),
        Column(
            "products_services",
            "Products and services",
            required=False,
            instructions="Text, up to 255 characters.",
        ),
        Column(
            "company_size_band",
            "Company size",
            required=False,
            instructions=f"One key: {_keys('COMPANY_SIZE')}.",
        ),
        Column(
            "employee_count",
            "Employees",
            required=False,
            instructions="A whole number, zero or greater.",
        ),
        Column(
            "annual_revenue",
            "Annual revenue",
            required=False,
            instructions=(
                "USD amount with at most two decimal places, such as 12500.50."
            ),
        ),
        Column(
            "rating",
            "Rating",
            required=False,
            instructions=f"One key: {_keys('LEAD_RATING')}. Blank means WARM.",
        ),
        Column(
            "owner",
            "Owner",
            required=False,
            instructions=OWNER_NOTE,
        ),
        Column(
            "notes",
            "Notes",
            required=False,
            instructions="Text, up to 4000 characters.",
        ),
    ]


def _account_columns():
    return [
        Column(
            "row_action",
            "Row action",
            required=False,
            instructions=(
                "Leave blank to import the row. Use example to keep a sample "
                "row; example rows are not imported."
            ),
        ),
        Column(
            "external_id",
            "External ID",
            required=False,
            instructions=(
                "Your own id. Letters, numbers, hyphens, or underscores, up to "
                "64 characters, and unique. Blank lets GlideCRM assign one."
            ),
        ),
        Column(
            "name",
            "Account name",
            required=True,
            instructions="Text, up to 200 characters.",
        ),
        Column(
            "account_type",
            "Account type",
            required=True,
            instructions=(
                f"One key: {_labeled(Account.Type.choices)}. "
                "Use the key, not the label."
            ),
        ),
        Column(
            "parent_external_id",
            "Parent account",
            required=False,
            instructions=(
                "external_id of the parent account. It must already exist, or "
                "appear on an earlier row in this file."
            ),
        ),
        Column(
            "industry",
            "Industry",
            required=False,
            instructions=(
                f"One key: {_labeled(TAXONOMY['INDUSTRY'])}. "
                "Use the key, not the label."
            ),
        ),
        Column(
            "website_url",
            "Website",
            required=False,
            instructions=(
                "example.com or https://example.com. An exact domain matches "
                "an existing account before the name does."
            ),
        ),
        Column(
            "phone",
            "Phone",
            required=False,
            instructions="Optional. 10 digits, stored as (XXX) XXX-XXXX.",
        ),
        *_address_columns(),
        Column(
            "owner",
            "Owner",
            required=False,
            instructions=OWNER_NOTE,
        ),
        Column(
            "notes",
            "Notes",
            required=False,
            instructions="Text.",
        ),
    ]


def _contact_columns():
    return [
        Column(
            "row_action",
            "Row action",
            required=False,
            instructions=(
                "Leave blank to import the row. Use example to keep a sample "
                "row; example rows are not imported."
            ),
        ),
        Column(
            "external_id",
            "External ID",
            required=False,
            instructions=(
                "Your own id. Letters, numbers, hyphens, or underscores, up to "
                "64 characters, and unique. Blank lets GlideCRM assign one."
            ),
        ),
        Column(
            "account_external_id",
            "Account",
            required=True,
            instructions=(
                "external_id of an account you can see. Import that account first."
            ),
        ),
        Column(
            "first_name",
            "First name",
            required=True,
            instructions="Text, up to 80 characters.",
        ),
        Column(
            "last_name",
            "Last name",
            required=True,
            instructions="Text, up to 80 characters.",
        ),
        Column(
            "title",
            "Title",
            required=False,
            instructions="Text, up to 120 characters.",
        ),
        Column(
            "email",
            "Email",
            required=True,
            instructions=(
                "name@domain. Used as the duplicate match when external_id is blank."
            ),
        ),
        Column(
            "work_phone",
            "Work phone",
            required=False,
            instructions="Optional. 10 digits, stored as (XXX) XXX-XXXX.",
        ),
        Column(
            "mobile_phone",
            "Mobile phone",
            required=False,
            instructions="Optional. 10 digits, stored as (XXX) XXX-XXXX.",
        ),
        *_address_columns(),
        Column(
            "is_primary",
            "Primary contact",
            required=False,
            instructions=(
                "true or false. Blank means false. One primary contact per account."
            ),
        ),
        Column(
            "reports_to_external_id",
            "Reports to",
            required=False,
            instructions=(
                "external_id of another contact at the same account. That contact "
                "must already exist, or appear on an earlier row."
            ),
        ),
        Column(
            "owner",
            "Owner",
            required=False,
            instructions=OWNER_NOTE,
        ),
        Column(
            "notes",
            "Notes",
            required=False,
            instructions="Text.",
        ),
    ]


COLUMNS = {
    "lead": _lead_columns(),
    "account": _account_columns(),
    "contact": _contact_columns(),
}

EXAMPLES = {
    "lead": {
        "row_action": "example",
        "external_id": "",
        "first_name": "Ada",
        "last_name": "Lovelace",
        "company_name": "Analytical Engines",
        "source": "WEB",
        "title": "Engineer",
        "email": "ada.lovelace@example.com",
        "work_phone": "(949) 555-0100",
        "mobile_phone": "",
        "street": "26040 Acero",
        "city": "Mission Viejo",
        "region": "CA",
        "postal_code": "92691",
        "country": "US",
        "website_url": "https://example.com",
        "industry": "INFORMATION_TECHNOLOGY",
        "products_services": "IT consulting",
        "company_size_band": "51_200",
        "employee_count": "120",
        "annual_revenue": "12500.50",
        "rating": "WARM",
        "owner": "",
        "notes": "Sample row. It is not imported while row_action is example.",
    },
    "account": {
        "row_action": "example",
        "external_id": "example-account",
        "name": "Analytical Engines",
        "account_type": "PROSPECT",
        "parent_external_id": "",
        "industry": "INFORMATION_TECHNOLOGY",
        "website_url": "https://example.com",
        "phone": "(949) 555-0100",
        "street": "26040 Acero",
        "city": "Mission Viejo",
        "region": "CA",
        "postal_code": "92691",
        "country": "US",
        "owner": "",
        "notes": "Sample row. It is not imported while row_action is example.",
    },
    "contact": {
        "row_action": "example",
        "external_id": "example-contact",
        "account_external_id": "example-account",
        "first_name": "Ada",
        "last_name": "Lovelace",
        "title": "Engineer",
        "email": "ada.lovelace@example.com",
        "work_phone": "(949) 555-0100",
        "mobile_phone": "(949) 555-0199",
        "street": "26040 Acero",
        "city": "Mission Viejo",
        "region": "CA",
        "postal_code": "92691",
        "country": "US",
        "is_primary": "true",
        "reports_to_external_id": "",
        "owner": "",
        "notes": "Sample row. Import the account template first if you reuse this id.",
    },
}

SHARED_NOTES = (
    "Save this file as UTF-8 CSV. "
    "Lines starting with # are instructions and are not imported.",
    "Keep the header row. Column names must stay as written.",
    "Dates, when a future template has them, use YYYY-MM-DD.",
    "Booleans use true or false.",
    "Do not start a cell with =, +, or @. A leading minus is allowed only on a number.",
    "Skip leaves a match unchanged. Update changes it. Create adds a new row.",
    "Matching uses external_id first, then an exact email, "
    "or an exact account domain or name. Similar names are not duplicates.",
    "Imported leads always start at New. Change the stage in GlideCRM after import.",
    "Error row numbers count the header as row 1 "
    "and do not count lines that start with #.",
)


def columns_for(entity):
    if entity not in COLUMNS:
        raise KeyError(entity)
    return COLUMNS[entity]


def template_csv(entity):
    """UTF-8 CSV text with instructions, a header, and one skipped example row."""
    columns = columns_for(entity)
    buffer = io.StringIO()
    for note in SHARED_NOTES:
        buffer.write(f"# {note}\n")
    for column in columns:
        requirement = "required" if column.required else "optional"
        buffer.write(f"# {column.key}: {requirement}. {column.instructions}\n")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([column.key for column in columns])
    example = EXAMPLES[entity]
    writer.writerow([example.get(column.key, "") for column in columns])
    return buffer.getvalue()
