# PDM — Property & Driver Management System

A full-featured property and driver management web application built with **Flask** and **PostgreSQL**. It manages tenants, monthly rent collection, drivers, daily ride logs, and personal/project finance — all behind a role-based login system with a modern dark UI (Bootstrap 5).

Built for a single owner/admin to run their entire rental property, vehicle fleet, and cash flow from one dashboard.

---

## Features

- **Authentication & Roles**
  - Register, login, forgot/reset password flows
  - Role-based access (`usertype`) with granular per-feature permissions:
    Master Admin, Admin, Users, Driver, Room Renter
  - Active/inactive user toggling with login blocking for deactivated accounts
- **Dashboard** — live stats (total / active / inactive users), user management, search, edit & toggle status
- **Rental Management**
  - Onboard tenants (Aadhaar, PAN, agreement PDF, property photos)
  - Record monthly rent with one-payment-per-month enforcement
  - Full payment ledger, history modal, correction audit trail (`last_updated_at`, `last_update_note`)
  - One-click **ZIP download** per tenant (professional PDF report + original documents)
- **Ride Management**
  - Register drivers (license, Aadhaar, vehicle, photos)
  - Record daily rides with meter start/end, odometer image, amount
  - Ride ledger, monthly stats, finance tab, driver history & edit/delete
- **Finance Management** — fixed deposits / other entries per bank, editable records, totals

---

## Tech Stack

| Layer      | Technology                                  |
|------------|---------------------------------------------|
| Backend    | Python 3, Flask                             |
| Database   | PostgreSQL 17                               |
| PDFs       | ReportLab (A4 MPDF-Input templates)         |
| Frontend   | Bootstrap 5.3, Bootstrap Icons, vanilla JS   |
| Styling    | Custom dark glassmorphism CSS               |

---

## Project Structure

```
PDM_Project/
├── app.py                    # Flask application, routes, schema init, PDF/ZIP generation
├── pdm_backup.sql            # Full PostgreSQL dump (schema + seed data)
├── requirements.txt
├── .env.example              # Environment variable template
├── static/
│   ├── css/                  # auth.css, style.css
│   └── uploads/              # Runtime-uploaded documents (gitignored)
├── templates/                # Jinja2 templates (login, dashboard, modules, etc.)
└── RENTAL_MANAGEMENT.md      # Deep-dive on the rental module
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- PostgreSQL 17 (running locally)
- pip

### 1. Database setup

Create a database and load the schema + seed data:

```bash
# Using the included dump (creates all tables with sample data)
psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE pdm;"
psql -U postgres -h 127.0.0.1 -d pdm -f pdm_backup.sql
```

> Alternatively, the app auto-creates missing tables on startup via `ensure_schema()` in `app.py`.

### 2. Environment variables

Copy `.env.example` to `.env` and set your real credentials:

```bash
SECRET_KEY=pdm_secret_key_2026
DB_HOST=127.0.0.1
DB_PORT=5432
DB_NAME=pdm
DB_USER=postgres
DB_PASSWORD=your_password_here
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run

```bash
python app.py
```

Open http://127.0.0.1:5000 and log in.

> **Default seed users** (from `pdm_backup.sql`): Master Admin `ajeetthakur706@gmail.com` / `Ajeet@123`. **Change passwords before any real use.**

---

## Database Structure

> Full schema, constraints, foreign keys and seed data are in [`pdm_backup.sql`](pdm_backup.sql).

### Tables overview

| Table                   | Purpose                                              |
|-------------------------|------------------------------------------------------|
| `usertype`              | Role definitions (Master Admin, Admin, Users, Driver, Room Renter) |
| `users`                 | Application users (login, profile, active status)    |
| `rentaldetails`         | Tenant KYC records (one per tenant)                  |
| `rentdetails`           | Monthly rent payment rows                            |
| `drivers`               | Driver KYC / license / vehicle records               |
| `ridedetails`           | Daily ride logs                                      |
| `finance_entries`       | Main finance ledger (Fixed Deposit / Others)         |
| `ride_finance_entries`  | Finance entries tied to the rides module             |
| `bank_master`           | Bank list for finance entries                        |
| `finance_type_master`   | Finance entry categories                             |

### Relationships

```
usertype 1──* users 1──1 rentaldetails 1──* rentdetails
                ├──1──1 drivers 1──* ridedetails
                └──1──* finance_entries
usertype 1──* users *──... ride_finance_entries
```

### Key tables

**users**

| Column     | Type             | Notes                                 |
|------------|------------------|---------------------------------------|
| id         | SERIAL PK        |                                       |
| firstname  | VARCHAR(100)     |                                       |
| lastname   | VARCHAR(100)     |                                       |
| email      | VARCHAR(255) UNIQUE | Login identifier                   |
| phone      | VARCHAR(20)      | 10-digit mobile                       |
| password   | TEXT             | Plain-text in current seeded version  |
| istype     | INT FK→usertype | Role                                 |
| isactive   | BOOLEAN DEFAULT TRUE | Login blocked when FALSE           |
| gender     | VARCHAR(10)      |                                       |
| created_at | TIMESTAMP        |                                       |

**rentaldetails**

| Column             | Type     | Notes                             |
|--------------------|----------|-----------------------------------|
| id                 | SERIAL PK |                                   |
| userid             | INT UNIQUE FK→users ON DELETE CASCADE | one tenant per user |
| usertypeid         | INT FK→usertype | copied from user          |
| aadharno           | VARCHAR(12) | 12 digits                        |
| rentagrement       | VARCHAR(255) | uploaded agreement PDF path   |
| panno              | VARCHAR(10) | PAN `ABCDE1234F`                |
| aadharimage/panimage/rentalimage | VARCHAR(255) | upload paths |
| floortype          | VARCHAR(50) | Ground / First / ...             |
| aadhar_address     | TEXT       |                                   |
| occupation         | VARCHAR(100) |                                   |
| total_member       | INT DEFAULT 1 |                                   |
| rental_joiningdate | DATE       |                                   |
| created_at         | TIMESTAMP |                                   |

**rentdetails** — one row per monthly payment

| Column      | Type          | Notes                                   |
|-------------|---------------|-----------------------------------------|
| id          | SERIAL PK     | Receipt number                          |
| rentalid    | INT FK→rentaldetails ON DELETE CASCADE | |
| year        | INT           | Accounting year                         |
| month       | SMALLINT      | 1–12, **UNIQUE(rentalid, year, month)** |
| rentamount  | NUMERIC(12,2) | Monthly rent                            |
| currentdate | TIMESTAMP     | Paid on                                 |
| last_updated_at / last_update_note | | Audit trail on correction |

**drivers**

| Column       | Type     | Notes                          |
|--------------|----------|--------------------------------|
| id           | SERIAL PK|                                |
| userid       | INT UNIQUE FK→users ON DELETE CASCADE | one driver per user |
| aadharno     | VARCHAR(12) |                              |
| license_no   | VARCHAR(30) |                              |
| vehicle_no   | VARCHAR(25) |                              |
| alt_phone    | VARCHAR(10), address TEXT |                    |
| dlimage / aadharimage / driverimage | VARCHAR(255) | upload paths |
| joiningdate  | DATE     |                                |

**ridedetails**

| Column      | Type           | Notes                          |
|-------------|----------------|--------------------------------|
| id          | SERIAL PK      |                                |
| driverid    | INT FK→drivers ON DELETE CASCADE |                      |
| ride_date   | DATE           |                                |
| km_driven   | NUMERIC(9,1)   | CHECK >= 0                     |
| meter_start / meter_end | NUMERIC(10,1) |                    |
| amount      | NUMERIC(12,2) DEFAULT 0 |                        |
| meter_image | VARCHAR(255)   | odometer photo path            |
| remarks     | TEXT           |                                |

**finance_entries** / **ride_finance_entries**

| Column      | Type          | Notes                                  |
|-------------|---------------|----------------------------------------|
| id          | SERIAL PK     |                                        |
| type_id     | INT FK→finance_type_master |                  |
| amount      | NUMERIC(12,2) | CHECK > 0                               |
| bank_name   | VARCHAR(80)   |                                        |
| fd_no       | VARCHAR(40)   | fixed deposit number                   |
| user_id     | INT FK→users ON DELETE SET NULL |              |
| entry_date / created_at / updated_at | | timestamps            |

**bank_master** — `id`, `bank_name UNIQUE`, `isactive`
**finance_type_master** — `id`, `type_name UNIQUE`, `isactive`

---

## Permissions Matrix

| Feature                      | Master Admin (1) | Admin (2) | Users (3) | Driver (4) | Room Renter (5) |
|------------------------------|:----------------:|:---------:|:---------:|:----------:|:---------------:|
| User management / toggle     | ✅               | ✅         | —         | —          | —               |
| Create user types            | ✅               | —         | —         | —          | —               |
| Register new accounts        | ✅               | —         | ✅         | —          | —               |
| Rental: add / history        | ✅               | ✅         | ✅         | —          | ✅               |
| Rental: correct / download   | ✅               | —         | —         | —          | —               |
| Ride: add driver / ride      | ✅               | ✅         | —         | ✅         | —               |
| Ride: edit (driver info)     | ✅               | ✅         | —         | —          | ✅               |
| Ride: delete driver / ride   | ✅               | —         | —         | —          | ✅               |
| Finance management           | ✅               | —         | —         | —          | ✅               |

---

## Security Notes

- **Deactivated users are blocked from logging in** (`isactive` check on login).
- Passwords are currently stored in plain text in the seeded database — **migrate to hashed passwords (bcrypt/werkzeug) before exposing the system beyond a personal setup.**
- Sensitive uploads (Aadhaar, PAN, agreements) live under `static/uploads/`; this folder is **gitignored**.
- DB credentials and the Flask secret key are read from environment variables (see `.env.example`). Never commit a real `.env`.

---

## License

Private project. All rights reserved.