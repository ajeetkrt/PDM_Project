# PDM — Rental Management Module

Monthly rent management system for the PDM project (Flask + PostgreSQL).
This module lives entirely inside the **Rental Management** page and does not modify any other page.

---

## 1. Module Overview

| Layer      | File(s)                                  | Responsibility |
|------------|------------------------------------------|----------------|
| Database   | PostgreSQL `pdm` DB (`ensure_schema()` in `app.py`) | Creates/repairs all tables at startup |
| Backend    | `app.py`                                 | Routes, validation, uploads, aggregations |
| UI         | `templates/RentalMangmt.html`            | Stats dashboard, tabs, tables, modals |
| Styling    | `static/css/style.css`                   | "Rental Management Module" section at the bottom |
| Documents  | `static/uploads/`                        | PDFs & images uploaded per tenant |

---

## 2. Database Structure

### Existing tables (unchanged)
- **users** — firstname, lastname, email, phone(mobile), password, created_at(created_on), gender, istype(usertype), isactive
- **usertype** — id, typename (e.g. Master Admin / Users / Driver / Room Renter)

### New table: `rentaldetails` (one row per tenant)

| Column               | Type             | Notes |
|----------------------|------------------|-------|
| id                   | SERIAL PK        | Rental record ID |
| userid               | INTEGER UNIQUE   | FK → users(id), ON DELETE CASCADE. One rental per user |
| usertypeid           | INTEGER          | FK → usertype(id). Copied automatically from the tenant's user type |
| aadharno             | VARCHAR(12)      | Exactly 12 digits, unique across tenants |
| rentagrement         | VARCHAR(255)     | Path to uploaded agreement PDF |
| panno                | VARCHAR(10)      | Format `ABCDE1234F` (optional) |
| aadharimage          | VARCHAR(255)     | Path to Aadhaar image |
| panimage             | VARCHAR(255)     | Path to PAN image |
| floortype            | VARCHAR(50)      | Ground / First / Second / Third |
| aadhar_address       | TEXT             | Address as printed on Aadhaar |
| occupation           | VARCHAR(100)     | Tenant occupation |
| total_member         | INTEGER          | Family members staying (>=1) |
| rentalimage          | VARCHAR(255)     | Property/room image |
| rental_joiningdate   | DATE             | Date the tenant moved in |
| created_at           | TIMESTAMP        | Record creation time |

### New table: `rentdetails` (one row per monthly rent payment)

| Column      | Type          | Notes |
|-------------|---------------|-------|
| id          | SERIAL PK     | Receipt number (#RD-0001 style) |
| year        | INTEGER       | Rent accounting year |
| month       | SMALLINT      | Rent month 1–12. **Unique per tenant + year + month** — one payment per calendar month |
| rentamount  | NUMERIC(12,2) | Monthly rent amount paid |
| currentdate | TIMESTAMP     | Defaults to NOW() when payment recorded |
| rentalid    | INTEGER       | FK → rentaldetails(id), ON DELETE CASCADE |

```
usertype 1──* users 1──1 rentaldetails 1──* rentdetails
                └─────────────┘ (usertypeid FK)
```

---

## 3. Backend Endpoints

| Method | Endpoint                  | Purpose |
|--------|---------------------------|---------|
| GET    | `/rental-management`      | Renders the module. Loads tenants + payments ledger + stats. Accepts `?year=YYYY` to filter the ledger |
| POST   | `/rental/create`          | Creates a tenant (multipart form with up to 4 file uploads). Returns JSON |
| POST   | `/rental/update`          | **Master Admin only.** Corrects an existing tenant's KYC/details; new uploads replace stored files |
| POST   | `/rental/payment/add`     | Records one monthly rent payment. Returns JSON |
| POST   | `/rental/payment/update`  | **Master Admin only.** Corrects an existing payment (month/year/amount); rejects duplicate periods. Stores a correction record (`last_updated_at`, `last_update_note` = "old period, amount → new period, amount") shown in History ("Updated: …") and inside the Correct Payment popup |
| POST   | `/rental/payment/delete`  | Deletes one payment row. Trash icon on every History row (Master Admin / Admin / Users), with a confirm prompt; history + Total Collected refresh inline after deletion |

**Payment audit trail:** every payment shows when it was *Added*; once corrected it also shows *Updated* date/time plus the exact change (e.g., `Sep 2026, ₹13,000.00 → Oct 2026, ₹16,000.00`). Clicking the edit icon in History closes the list and opens the Correct Payment popup alone, with that payment's add/correction info at the top.
| GET    | `/rental/payments/<id>`   | JSON: tenant KYC info + full payment history for History modal |
| GET    | `/rental/download/<id>`   | **Master Admin only.** One-click ZIP download per tenant: professional PDF report (full tenant details, complete payment ledger with amounts, embedded Aadhaar/PAN/property photos) + original Aadhaar image, PAN image and Rent Agreement files |

**Access rule:** edit/correct actions are restricted to the Master Admin (usertype id 1) — enforced server-side via `_require_master_admin()` and hidden in the UI for everyone else.

### Validation rules (client + server mirrored)
- Tenant must be an existing **active** user without an existing rental record
- Aadhaar: exactly 12 digits, not already registered
- PAN: optional, but must match `ABCDE1234F` if provided
- Total members >= 1; Joining date required
- Files: agreement `.pdf`; images `.png/.jpg/.jpeg/.webp`; max **5 MB** each
- Payment: valid month (1–12), valid year 2000–2100, amount > 0; duplicate month for the same tenant/year is rejected ("already recorded")

### File storage
Uploads are saved to `static/uploads/<uuid>.<ext>`; only the relative path is stored in the database.

---

## 4. UI Structure (RentalMangmt.html)

1. **Navbar** — Add Rental button opens the tenant modal; Rent Ledger jumps to the ledger tab
2. **Sidebar** — payment-year filter, live overview numbers, quick links
3. **Profile strip** — logged-in user + their user-type badge
4. **Stat cards** — Total Tenants, Members Housed, This Month Collection, Lifetime Collection
5. **Tabs**
   - *Tenants*: searchable table (masked Aadhaar `**** **** 1234`, floor, members, joining date, total paid ₹ + months chip) with actions **Add Rent** and **History**
   - *Rent Ledger*: receipt-wise payment register (#RD-xxxx, tenant, year, amount, paid-on)
6. **Modals** — Add Tenant (KYC + documents), Record Rent Payment, Tenant History (info grid, document chips, payment timeline, total collected)

---

## 5. Test Flow

1. Login → Rental Management
2. Add Tenant → pick a user, fill KYC, attach PDF/images → Save
3. Row appears in Tenants tab with masked Aadhaar and ₹0.00 paid
4. Add Rent → enter year + amount → Save
5. Stat cards and Total Paid update; entry visible in Rent Ledger
6. History → view KYC, documents and complete payment timeline
