from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file, g
import psycopg2
import psycopg2.extras
import re
import os
import io
import uuid
import zipfile
import hashlib
import secrets
from datetime import datetime, date, timezone, timedelta

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                Image as RLImage)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'pdm_secret_key_2026')

UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

_ALLOWED_PDF_EXT = {'pdf'}
_ALLOWED_IMG_EXT = {'png', 'jpg', 'jpeg', 'webp'}

DB_CONFIG = {
    'host': os.environ.get('DB_HOST', '127.0.0.1'),
    'port': int(os.environ.get('DB_PORT', '5432')),
    'database': os.environ.get('DB_NAME', 'pdm'),
    'user': os.environ.get('DB_USER', 'postgres'),
    'password': os.environ.get('DB_PASSWORD', ''),
    'connect_timeout': int(os.environ.get('DB_CONNECT_TIMEOUT', '3'))
}

_email_re = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
_phone_re = re.compile(r'^[0-9]{10}$')


def get_db():
    conn = psycopg2.connect(**DB_CONFIG, cursor_factory=psycopg2.extras.RealDictCursor)
    return conn


def ensure_schema():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS isactive BOOLEAN NOT NULL DEFAULT TRUE
        """)
        cursor.execute("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS gender VARCHAR(10)
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usertype (
                id SERIAL PRIMARY KEY,
                typename VARCHAR(50) UNIQUE NOT NULL
            )
        """)
        cursor.execute("""
            INSERT INTO usertype (typename)
            SELECT 'Admin' WHERE NOT EXISTS (SELECT 1 FROM usertype)
        """)
        cursor.execute("""
            INSERT INTO usertype (typename)
            SELECT 'User' WHERE NOT EXISTS (SELECT 1 FROM usertype)
        """)
        for _seed_name in ('Master Admin', 'Admin', 'Users', 'Driver', 'Room Renter'):
            cursor.execute("""
                INSERT INTO usertype (typename)
                SELECT %s WHERE NOT EXISTS (SELECT 1 FROM usertype WHERE typename = %s)
            """, (_seed_name, _seed_name))
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rentaldetails (
                id SERIAL PRIMARY KEY,
                userid INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                usertypeid INTEGER REFERENCES usertype(id),
                aadharno VARCHAR(12) NOT NULL,
                rentagrement VARCHAR(255),
                panno VARCHAR(10),
                aadharimage VARCHAR(255),
                panimage VARCHAR(255),
                floortype VARCHAR(50),
                aadhar_address TEXT,
                occupation VARCHAR(100),
                total_member INTEGER NOT NULL DEFAULT 1,
                rentalimage VARCHAR(255),
                rental_joiningdate DATE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rentdetails (
                id SERIAL PRIMARY KEY,
                year INTEGER NOT NULL,
                rentamount NUMERIC(12,2) NOT NULL,
                currentdate TIMESTAMP NOT NULL DEFAULT NOW(),
                rentalid INTEGER NOT NULL REFERENCES rentaldetails(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS drivers (
                id SERIAL PRIMARY KEY,
                userid INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                usertypeid INTEGER REFERENCES usertype(id),
                aadharno VARCHAR(12) NOT NULL,
                license_no VARCHAR(30) NOT NULL,
                vehicle_no VARCHAR(25),
                alt_phone VARCHAR(10),
                address TEXT,
                dlimage VARCHAR(255),
                aadharimage VARCHAR(255),
                driverimage VARCHAR(255),
                joiningdate DATE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ridedetails (
                id SERIAL PRIMARY KEY,
                driverid INTEGER NOT NULL REFERENCES drivers(id) ON DELETE CASCADE,
                ride_date DATE NOT NULL DEFAULT CURRENT_DATE,
                km_driven NUMERIC(9,1) NOT NULL CHECK (km_driven >= 0),
                meter_start NUMERIC(10,1),
                meter_end NUMERIC(10,1),
                meter_image VARCHAR(255),
                amount NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (amount >= 0),
                remarks TEXT,
                currentdate TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ride_finance_entries (
                id SERIAL PRIMARY KEY,
                type_id INT,
                amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
                bank_name VARCHAR(80) NOT NULL,
                fd_no VARCHAR(40),
                user_id INT REFERENCES users(id) ON DELETE SET NULL,
                remarks TEXT,
                entry_date DATE NOT NULL DEFAULT CURRENT_DATE,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except Exception:
        pass


ensure_schema()


def _sync_users_id_sequence():
    """Ensure users.id serial sequence is ahead of MAX(id) to avoid PK clashes."""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT setval(
                pg_get_serial_sequence('users', 'id'),
                GREATEST((SELECT COALESCE(MAX(id), 0) FROM users), 1),
                (SELECT COALESCE(MAX(id), 0) FROM users) > 0
            )
        """)
        conn.commit()
        cursor.close()
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn:
            conn.close()


def _sync_usertype_id_sequence():
    """Ensure usertype.id serial sequence is ahead of MAX(id) to avoid PK clashes."""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT setval(
                pg_get_serial_sequence('usertype', 'id'),
                GREATEST((SELECT COALESCE(MAX(id), 0) FROM usertype), 1),
                (SELECT COALESCE(MAX(id), 0) FROM usertype) > 0
            )
        """)
        conn.commit()
        cursor.close()
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn:
            conn.close()


_sync_users_id_sequence()
_sync_usertype_id_sequence()


def _ensure_rent_months():
    """Add month tracking to rentdetails and enforce one payment per tenant/month/year."""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            ALTER TABLE rentdetails
            ADD COLUMN IF NOT EXISTS month SMALLINT NOT NULL DEFAULT EXTRACT(MONTH FROM CURRENT_DATE)
        """)
        cursor.execute("""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_rentdetails_period') THEN
                    ALTER TABLE rentdetails ADD CONSTRAINT uq_rentdetails_period UNIQUE (rentalid, year, month);
                END IF;
            END $$;
        """)
        conn.commit()
        cursor.close()
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn:
            conn.close()


def _ensure_payment_audit():
    """Track when a rent payment was corrected and what changed."""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("ALTER TABLE rentdetails ADD COLUMN IF NOT EXISTS last_updated_at TIMESTAMP")
        cursor.execute("ALTER TABLE rentdetails ADD COLUMN IF NOT EXISTS last_update_note TEXT")
        conn.commit()
        cursor.close()
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn:
            conn.close()


_ensure_rent_months()
_ensure_payment_audit()

_FIN_TYPES_SEED = ('Fixed Deposit', 'Others')
_FIN_BANKS = ['State Bank of India', 'HDFC Bank', 'ICICI Bank', 'Punjab National Bank',
              'Axis Bank', 'Kotak Mahindra Bank', 'Bank of Baroda', 'Canara Bank',
              'Union Bank of India', 'IDBI Bank', 'IndusInd Bank', 'Federal Bank',
              'IDFC FIRST Bank', 'Bandhan Bank', 'Yes Bank', 'Other']


def _ensure_finance_entries():
    """Finance management page: tracked allocations of collected rental amounts."""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS finance_entries (
                id SERIAL PRIMARY KEY,
                type_id INT,
                amount NUMERIC(12,2) NOT NULL CHECK (amount > 0),
                bank_name VARCHAR(80) NOT NULL,
                fd_no VARCHAR(40),
                user_id INT REFERENCES users(id) ON DELETE SET NULL,
                remarks TEXT,
                entry_date DATE NOT NULL DEFAULT CURRENT_DATE,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP
            )
        """)
        cursor.execute("ALTER TABLE finance_entries ADD COLUMN IF NOT EXISTS fd_no VARCHAR(40)")
        conn.commit()
        cursor.close()
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn:
            conn.close()


def _ensure_finance_masters():
    """Master tables for managed-amount types and banks, seeded once."""
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS finance_type_master (
                id SERIAL PRIMARY KEY,
                type_name VARCHAR(50) NOT NULL UNIQUE,
                isactive BOOLEAN NOT NULL DEFAULT TRUE
            )
        """)
        cursor.execute("SELECT COALESCE(array_agg(type_name), '{}') AS names FROM finance_type_master")
        existing = set(cursor.fetchone()['names'] or [])
        for t in _FIN_TYPES_SEED:
            if t not in existing:
                cursor.execute('INSERT INTO finance_type_master (type_name) VALUES (%s)', (t,))

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bank_master (
                id SERIAL PRIMARY KEY,
                bank_name VARCHAR(80) NOT NULL UNIQUE,
                isactive BOOLEAN NOT NULL DEFAULT TRUE
            )
        """)
        cursor.execute('SELECT COALESCE(array_agg(bank_name), %s) AS names FROM bank_master', ([],))
        existing_banks = set(cursor.fetchone()['names'] or [])
        for b in _FIN_BANKS:
            if b not in existing_banks:
                cursor.execute('INSERT INTO bank_master (bank_name) VALUES (%s)', (b,))

        cursor.execute('ALTER TABLE finance_entries ADD COLUMN IF NOT EXISTS type_id INT')
        cursor.execute("""
            UPDATE finance_entries fe
            SET type_id = tm.id
            FROM finance_type_master tm
            WHERE fe.type_id IS NULL
              AND ((fe.category = 'Fixed Deposit' AND tm.type_name = 'Fixed Deposit')
                OR (fe.category = 'Others' AND tm.type_name = 'Others'))
        """)
        cursor.execute('ALTER TABLE finance_entries DROP CONSTRAINT IF EXISTS finance_entries_category_check')
        cursor.execute('ALTER TABLE finance_entries DROP COLUMN IF EXISTS category')
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_fe_type') THEN
                    ALTER TABLE finance_entries
                        ADD CONSTRAINT fk_fe_type FOREIGN KEY (type_id)
                        REFERENCES finance_type_master(id);
                END IF;
            END $$;
        """)
        conn.commit()
        cursor.close()
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn:
            conn.close()


_ensure_finance_entries()
_ensure_finance_masters()


@app.before_request
def before_request():
    session.permanent = False


@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        errors = {}

        if not email:
            errors['email'] = 'Email is required.'
        elif not _email_re.match(email):
            errors['email'] = 'Please enter a valid email address.'

        if not password:
            errors['password'] = 'Password is required.'
        elif len(password) < 6:
            errors['password'] = 'Password must be at least 6 characters.'

        if errors:
            return render_template('login.html', errors=errors, email=email)

        conn = None
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT id, firstname, lastname, email, password, isactive FROM users WHERE email = %s LIMIT 1', (email,))
            user = cursor.fetchone()
            cursor.close()
        except Exception:
            errors['general'] = 'Database error. Please try again.'
            return render_template('login.html', errors=errors, email=email)
        finally:
            if conn:
                conn.close()

        if user and not user['isactive']:
            errors['general'] = 'Your account has been deactivated. Please contact the administrator.'
            return render_template('login.html', errors=errors, email=email)

        if user and user['password'] == password:
            session['user_id'] = user['id']
            session['firstname'] = user['firstname']
            session['lastname'] = user['lastname']
            session['email'] = user['email']
            return redirect(url_for('dashboard'))
        else:
            errors['general'] = 'Invalid email or password.'
            return render_template('login.html', errors=errors, email=email)

    return render_template('login.html', errors={}, email='')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        firstname = request.form.get('firstname', '').strip()
        lastname = request.form.get('lastname', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        gender = request.form.get('gender', '')
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        errors = {}

        if gender not in ('Male', 'Female', 'Other'):
            errors['gender'] = 'Please select your gender.'

        if not firstname:
            errors['firstname'] = 'First name is required.'
        elif len(firstname) < 2:
            errors['firstname'] = 'First name must be at least 2 characters.'

        if not lastname:
            errors['lastname'] = 'Last name is required.'
        elif len(lastname) < 2:
            errors['lastname'] = 'Last name must be at least 2 characters.'

        if not email:
            errors['email'] = 'Email is required.'
        elif not _email_re.match(email):
            errors['email'] = 'Please enter a valid email address.'

        if not phone:
            errors['phone'] = 'Phone number is required.'
        elif not _phone_re.match(phone):
            errors['phone'] = 'Please enter a valid 10-digit phone number.'

        if not password:
            errors['password'] = 'Password is required.'
        elif len(password) < 6:
            errors['password'] = 'Password must be at least 6 characters.'
        elif not any(c.isupper() for c in password):
            errors['password'] = 'Password must contain at least one uppercase letter.'
        elif not any(c.isdigit() for c in password):
            errors['password'] = 'Password must contain at least one number.'

        if not confirm_password:
            errors['confirm_password'] = 'Please confirm your password.'
        elif password != confirm_password:
            errors['confirm_password'] = 'Passwords do not match.'

        if not errors:
            conn = None
            try:
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute(
                    'INSERT INTO users (firstname, lastname, email, phone, gender, password, istype) VALUES (%s, %s, %s, %s, %s, %s, %s)',
                    (firstname, lastname, email, phone, gender, password, 2)
                )
                conn.commit()
                flash('Registration successful! Please login.', 'success')
                return redirect(url_for('login'))
            except psycopg2.IntegrityError:
                conn.rollback()
                errors['email'] = 'Email already registered.'
            except Exception:
                if conn:
                    conn.rollback()
            finally:
                if conn:
                    conn.close()

        return render_template('register.html', errors=errors,
                               firstname=firstname, lastname=lastname,
                               email=email, phone=phone, gender=gender)

    return render_template('register.html', errors={}, firstname='',
                           lastname='', email='', phone='', gender='')


_PW_RESET_EXPIRY_MINUTES = 30


def _hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _ensure_reset_tokens():
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id SERIAL PRIMARY KEY,
                token_hash VARCHAR(64) NOT NULL UNIQUE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at TIMESTAMPTZ NOT NULL,
                used BOOLEAN NOT NULL DEFAULT FALSE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        conn.commit()
        cursor.close()
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn:
            conn.close()


_ensure_reset_tokens()


def _lookup_reset_token(token):
    """Return the user id for a valid, unexpired reset token, else None."""
    if not token or len(token) > 128:
        return None
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_id FROM password_reset_tokens
            WHERE token_hash = %s AND used = FALSE AND expires_at > NOW()
            LIMIT 1
        """, (_hash_token(token),))
        row = cursor.fetchone()
        cursor.close()
        return row['user_id'] if row else None
    except Exception:
        app.logger.exception('reset token lookup failed')
        return None
    finally:
        if conn:
            conn.close()


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    errors = {}
    email = ''
    reset_link = None
    submitted = False

    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        submitted = True

        if not email:
            errors['email'] = 'Email is required.'
        elif not _email_re.match(email):
            errors['email'] = 'Please enter a valid email address.'

        if not errors:
            conn = None
            try:
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute('SELECT id FROM users WHERE email = %s LIMIT 1', (email,))
                row = cursor.fetchone()
                if row:
                    cursor.execute("""
                        DELETE FROM password_reset_tokens
                        WHERE user_id = %s AND (used = TRUE OR expires_at <= NOW())
                    """, (row['id'],))
                    token = secrets.token_urlsafe(32)
                    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_PW_RESET_EXPIRY_MINUTES)
                    cursor.execute("""
                        INSERT INTO password_reset_tokens (token_hash, user_id, expires_at)
                        VALUES (%s, %s, %s)
                    """, (_hash_token(token), row['id'], expires_at))
                    conn.commit()
                    reset_link = url_for('reset_password', token=token)
                cursor.close()
            except Exception:
                errors['general'] = 'Database error. Please try again.'
            finally:
                if conn:
                    conn.close()

    return render_template('forgot.html', errors=errors, email=email,
                           reset_link=reset_link, submitted=submitted,
                           expiry_minutes=_PW_RESET_EXPIRY_MINUTES)


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if 'user_id' in session:
        return redirect(url_for('dashboard'))

    user_id = _lookup_reset_token(token)
    if user_id is None:
        return render_template('reset.html',
                               errors={'general': 'This reset link is invalid or has expired. Please request a new one.'},
                               token=token)

    if request.method == 'POST':
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        errors = {}

        if not password:
            errors['password'] = 'Password is required.'
        elif len(password) < 6:
            errors['password'] = 'Password must be at least 6 characters.'
        elif not any(c.isupper() for c in password):
            errors['password'] = 'Password must contain at least one uppercase letter.'
        elif not any(c.isdigit() for c in password):
            errors['password'] = 'Password must contain at least one number.'

        if not confirm_password:
            errors['confirm_password'] = 'Please confirm your password.'
        elif password != confirm_password:
            errors['confirm_password'] = 'Passwords do not match.'

        if not errors:
            conn = None
            try:
                conn = get_db()
                cursor = conn.cursor()
                cursor.execute('UPDATE users SET password = %s WHERE id = %s', (password, user_id))
                cursor.execute('UPDATE password_reset_tokens SET used = TRUE WHERE token_hash = %s',
                               (_hash_token(token),))
                conn.commit()
                cursor.close()
                flash('Your password has been reset successfully. Please sign in.', 'success')
                return redirect(url_for('login'))
            except Exception:
                if conn:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                errors['general'] = 'Database error. Please try again.'
            finally:
                if conn:
                    conn.close()

        return render_template('reset.html', errors=errors, token=token)

    return render_template('reset.html', errors={}, token=token)


def _load_user_types():
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id, typename FROM usertype ORDER BY id')
        rows = cursor.fetchall()
        cursor.close()
        return rows
    except Exception:
        return []
    finally:
        if conn:
            conn.close()


def _is_valid_type(istype):
    if not istype or not istype.isdigit():
        return False
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM usertype WHERE id = %s LIMIT 1', (int(istype),))
        row = cursor.fetchone()
        cursor.close()
        return bool(row)
    except Exception:
        return False
    finally:
        if conn:
            conn.close()


def _is_email_unique_violation(err):
    """True only when the IntegrityError is genuinely an email-unique clash."""
    if getattr(err, 'pgcode', None) != '23505':
        return False
    diag = getattr(err, 'diag', None)
    cname = (getattr(diag, 'constraint_name', '') or '').lower()
    pmsg = (getattr(diag, 'message_primary', '') or '').lower()
    return 'email' in cname or 'email' in pmsg


def _is_pk_violation(err):
    return getattr(err, 'pgcode', None) == '23505' and \
        'pkey' in ((getattr(err.diag, 'constraint_name', '') or '').lower())


def _load_users_overview(filter_type='', filter_year=''):
    users = []
    years = []
    stats = {'total': 0, 'active': 0, 'inactive': 0}
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT DISTINCT EXTRACT(YEAR FROM created_at)::int AS yr FROM users ORDER BY yr DESC")
        years = [row['yr'] for row in cursor.fetchall()]

        cursor.execute("""
            SELECT
                COUNT(*)::int AS total,
                COUNT(*) FILTER (WHERE isactive)::int AS active,
                COUNT(*) FILTER (WHERE NOT isactive)::int AS inactive
            FROM users
        """)
        stats = cursor.fetchone()

        query = """
            SELECT u.id, u.firstname, u.lastname, u.email, u.phone, u.gender,
                   u.istype, ut.typename AS type_name, u.isactive, u.created_at
            FROM users u
            LEFT JOIN usertype ut ON u.istype = ut.id
        """
        conditions = []
        params = []
        if filter_type and filter_type.isdigit():
            conditions.append('u.istype = %s')
            params.append(int(filter_type))
        if filter_year and filter_year.isdigit():
            conditions.append('EXTRACT(YEAR FROM u.created_at) = %s')
            params.append(int(filter_year))
        if conditions:
            query += ' WHERE ' + ' AND '.join(conditions)
        query += ' ORDER BY u.created_at DESC'
        cursor.execute(query, tuple(params))
        users = cursor.fetchall()
        cursor.close()
    except Exception:
        flash('Database error while loading users.', 'danger')
    finally:
        if conn:
            conn.close()
    return users, years, stats


def _get_current_user_type():
    if 'user_id' not in session:
        return None
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT istype FROM users WHERE id = %s LIMIT 1', (int(session['user_id']),))
        row = cursor.fetchone()
        cursor.close()
        if row:
            return row['istype']
    except Exception:
        pass
    finally:
        if conn:
            conn.close()
    return None


def _get_current_user_type_name():
    if 'user_id' not in session:
        return ''
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ut.typename
            FROM users u JOIN usertype ut ON u.istype = ut.id
            WHERE u.id = %s LIMIT 1
        """, (int(session['user_id']),))
        row = cursor.fetchone()
        cursor.close()
        if row:
            return row['typename']
    except Exception:
        pass
    finally:
        if conn:
            conn.close()
    return ''


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    me_t = _get_current_user_type()
    if me_t not in (_rid('Master Admin'), _rid('Admin'), _rid('Users')):
        if me_t == _rid('Driver'):
            return redirect(url_for('rides_management'))
        return redirect(url_for('rental_management'))

    filter_type = request.args.get('usertype', '')
    filter_year = request.args.get('year', '')
    users, years, stats = _load_users_overview(filter_type, filter_year)
    me_type = _get_current_user_type()
    types = _load_user_types()

    return render_template('dashboard.html', users=users, years=years,
                           stats=stats, filter_type=filter_type, filter_year=filter_year,
                           me_type=me_type, me_type_name=_get_current_user_type_name(), types=types)


_aadhar_re = re.compile(r'^[0-9]{12}$')
_pan_re = re.compile(r'^[A-Z]{5}[0-9]{4}[A-Z]$')
_MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
                'August', 'September', 'October', 'November', 'December']

_PDF_FONT = 'Helvetica'
_PDF_FONT_B = 'Helvetica-Bold'
for _font_pair in ((r'C:\Windows\Fonts\arial.ttf', r'C:\Windows\Fonts\arialbd.ttf'),
                   (r'C:\Windows\Fonts\segoeui.ttf', r'C:\Windows\Fonts\segoeuib.ttf')):
    if all(os.path.exists(p) for p in _font_pair):
        try:
            pdfmetrics.registerFont(TTFont('PDMFont', _font_pair[0]))
            pdfmetrics.registerFont(TTFont('PDMFont-Bold', _font_pair[1]))
            _PDF_FONT, _PDF_FONT_B = 'PDMFont', 'PDMFont-Bold'
        except Exception:
            pass
        break


def _money_str(value):
    s = f'\u20b9 {float(value):,.2f}'
    return s.replace('\u20b9', 'Rs.') if _PDF_FONT == 'Helvetica' else s


_PDF_INK = colors.HexColor('#0f172a')
_PDF_MUTED = colors.HexColor('#64748b')
_PDF_ACCENT = colors.HexColor('#4f46e5')
_PDF_ACCENT_DARK = colors.HexColor('#312e81')
_PDF_BAND_BG = colors.HexColor('#1e1b4b')
_PDF_LINE = colors.HexColor('#e2e8f0')
_PDF_ZEBRA = colors.HexColor('#f8fafc')


def _scaled_image(rel_path, max_w, max_h):
    if not rel_path:
        return None
    fp = os.path.join(app.static_folder, rel_path)
    if not os.path.exists(fp):
        return None
    try:
        from PIL import Image as PILImage
        with PILImage.open(fp) as im:
            w, h = im.size
        scale = min(max_w / float(w), max_h / float(h), 1.0)
        return RLImage(fp, width=float(w) * scale, height=float(h) * scale)
    except Exception:
        return None


def _pdf_section(title):
    t = Table([[Paragraph(title, ParagraphStyle(
        'sec', fontName=_PDF_FONT_B, fontSize=10.5, leading=13, textColor=_PDF_INK))]],
        colWidths=[178 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#eef2ff')),
        ('LINEBEFORE', (0, 0), (0, 0), 3, _PDF_ACCENT),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    return t


def _build_rental_pdf(rental, payments):
    """Compose a professional A4 rental report for one tenant. Returns BytesIO of PDF bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=18 * mm,
                            title=f'Tenant Rental Report - {rental["full_name"]}',
                            author='PDM Rental Management')

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setStrokeColor(_PDF_LINE)
        canvas.setLineWidth(0.7)
        canvas.line(16 * mm, 13 * mm, A4[0] - 16 * mm, 13 * mm)
        canvas.setFont(_PDF_FONT, 7.5)
        canvas.setFillColor(_PDF_MUTED)
        canvas.drawString(16 * mm, 9 * mm, 'PDM \u2022 Rental Management \u2014 system generated document')
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f'Page {doc_.page}')
        canvas.restoreState()

    story = []

    head_left = [
        Paragraph('<font color="#a5b4fc">PDM RENTAL MANAGEMENT</font>',
                  ParagraphStyle('k', fontName=_PDF_FONT_B, fontSize=8, leading=10)),
        Spacer(1, 4),
        Paragraph('<font color="white">Tenant Rental Report</font>',
                  ParagraphStyle('t', fontName=_PDF_FONT_B, fontSize=17, leading=21)),
    ]
    gen_stamp = datetime.now().strftime('%d %b %Y, %I:%M %p')
    right_style = ParagraphStyle('r', fontName=_PDF_FONT, fontSize=8.5, leading=12, alignment=TA_RIGHT)
    head_right = [
        Paragraph(f'<font color="#c7d2fe">Report Ref</font><br/><font color="white"><b>#RPT-{rental["id"]:04d}</b></font>', right_style),
        Spacer(1, 4),
        Paragraph(f'<font color="#c7d2fe">Generated On</font><br/><font color="white"><b>{gen_stamp}</b></font>', right_style),
    ]
    head = Table([[head_left, head_right]], colWidths=[110 * mm, 68 * mm])
    head.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), _PDF_BAND_BG),
        ('LINEBELOW', (0, 0), (-1, -1), 2.5, _PDF_ACCENT),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 11),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 11),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
    ]))
    story.append(head)
    story.append(Spacer(1, 9))

    total_collected = sum(float(p['rentamount']) for p in payments)
    story.append(Table([[
        [Paragraph(rental['full_name'], ParagraphStyle('nm', fontName=_PDF_FONT_B, fontSize=14, leading=17, textColor=_PDF_INK)),
         Paragraph(f"{rental.get('type_name') or 'Member'} \u2022 Joined {rental['joining_label']}",
                   ParagraphStyle('nms', fontName=_PDF_FONT, fontSize=8.5, leading=11, textColor=_PDF_MUTED))],
        [Paragraph(f'<font size="7.5" color="#64748b">TOTAL COLLECTED TO DATE</font>',
                   ParagraphStyle('tc0', fontName=_PDF_FONT, fontSize=7.5, leading=9, alignment=TA_RIGHT)),
         Paragraph(f'<font color="#16a34a"><b>{_money_str(total_collected)}</b></font> '
                   f'<font size="7" color="#94a3b8">/ {len(payments)} payment(s)</font>',
                   ParagraphStyle('tc1', fontName=_PDF_FONT_B, fontSize=11.5, leading=14, alignment=TA_RIGHT))],
    ]], colWidths=[110 * mm, 68 * mm], style=TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ])))
    story.append(Spacer(1, 10))

    story.append(_pdf_section('TENANT DETAILS'))
    story.append(Spacer(1, 5))
    lbl_style = ParagraphStyle('lb', fontName=_PDF_FONT, fontSize=7.2, leading=9, textColor=_PDF_MUTED)
    val_style = ParagraphStyle('vl', fontName=_PDF_FONT_B, fontSize=9.2, leading=12, textColor=_PDF_INK)

    def pair(label, value):
        return [Paragraph(label.upper(), lbl_style), Paragraph(str(value or '-'), val_style)]

    info_grid = Table([
        pair('Email', rental['email']) + pair('Phone', rental['phone']),
        pair('Aadhaar No', rental['aadharno']) + pair('PAN No', rental['panno']),
        pair('Floor', rental['floortype']) + pair('Total Members', rental['total_member']),
        pair('Occupation', rental['occupation']) + pair('Joining Date', rental['joining_label']),
        pair('Aadhaar Address', rental['aadhar_address']) + ['', ''],
    ], colWidths=[32 * mm, 57 * mm, 32 * mm, 57 * mm])
    info_grid.setStyle(TableStyle([
        ('SPAN', (1, 4), (3, 4)),
        ('GRID', (0, 0), (-1, -1), 0.5, _PDF_LINE),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, _PDF_ZEBRA]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.append(info_grid)
    story.append(Spacer(1, 12))

    story.append(_pdf_section('PAYMENT HISTORY'))
    story.append(Spacer(1, 5))
    th = ParagraphStyle('th', fontName=_PDF_FONT_B, fontSize=8, leading=10, textColor=colors.white)
    td = ParagraphStyle('td', fontName=_PDF_FONT, fontSize=8.5, leading=11, textColor=_PDF_INK)
    td_r = ParagraphStyle('tdr', parent=td, alignment=TA_RIGHT)
    td_mut = ParagraphStyle('tdm', parent=td, fontSize=7.6, textColor=_PDF_MUTED)
    pay_rows = [[Paragraph(h, th) for h in ['Receipt', 'Period', 'Amount', 'Added On', 'Last Updated']]]
    for p in payments:
        period = f"{_MONTH_NAMES[(p['month'] or 1) - 1][:3]} {p['year']}"
        updated_cell = Paragraph(p['updated_on'] or '-', td_mut)
        if p.get('update_note'):
            updated_cell = Paragraph(f"{p['updated_on']}<br/><font size='6.4' color='#94a3b8'>{p['update_note']}</font>", td_mut)
        pay_rows.append([
            Paragraph(f"#RD-{p['id']:04d}", td),
            Paragraph(period, td),
            Paragraph(f"<font color='#16a34a'><b>{_money_str(p['rentamount'])}</b></font>", td_r),
            Paragraph(p['added_on'], td_mut),
            updated_cell,
        ])
    pay_rows.append([
        '', '',
        Paragraph(f'<font color="#16a34a"><b>{_money_str(total_collected)}</b></font>', td_r),
        Paragraph('<b>TOTAL</b>', ParagraphStyle('tt', parent=td_r)),
        '',
    ])
    pay_tbl = Table(pay_rows, colWidths=[22 * mm, 24 * mm, 34 * mm, 46 * mm, 52 * mm], repeatRows=1)
    pay_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), _PDF_ACCENT_DARK),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, _PDF_ZEBRA]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#ecfdf5')),
        ('LINEABOVE', (0, -1), (-1, -1), 0.8, colors.HexColor('#16a34a')),
        ('SPAN', (0, -1), (1, -1)),
        ('GRID', (0, 0), (-1, -1), 0.5, _PDF_LINE),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 7),
    ]))
    if len(payments) == 0:
        story.append(Paragraph('No payments recorded yet.', ParagraphStyle(
            'np', fontName=_PDF_FONT, fontSize=9, textColor=_PDF_MUTED)))
    else:
        story.append(pay_tbl)
    story.append(Spacer(1, 12))

    story.append(_pdf_section('KYC DOCUMENTS'))
    story.append(Spacer(1, 6))
    cap_style = ParagraphStyle('cap', fontName=_PDF_FONT_B, fontSize=8, leading=10,
                               alignment=TA_CENTER, textColor=_PDF_INK)
    miss_style = ParagraphStyle('ms', fontName=_PDF_FONT, fontSize=8, leading=10,
                                alignment=TA_CENTER, textColor=_PDF_MUTED)
    doc_cells = []
    for key, caption in (('aadharimage', 'Aadhaar Card'), ('panimage', 'PAN Card'),
                         ('rentalimage', 'Property / Room Photo')):
        img = _scaled_image(rental.get(key), 54 * mm, 40 * mm)
        cell = [img if img else Paragraph('[ Not uploaded ]', miss_style), Spacer(1, 3),
                Paragraph(caption, cap_style)]
        doc_cells.append(cell)
    doc_tbl = Table([doc_cells], colWidths=[59.3 * mm] * 3)
    doc_tbl.setStyle(TableStyle([
        ('BOX', (0, 0), (0, 0), 0.5, _PDF_LINE),
        ('BOX', (1, 0), (1, 0), 0.5, _PDF_LINE),
        ('BOX', (2, 0), (2, 0), 0.5, _PDF_LINE),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(doc_tbl)
    story.append(Spacer(1, 6))
    agree_txt = ('Rent agreement attached separately in this download package as '
                 f'"Rent_Agreement_{rental["safe_name"]}.pdf".'
                 if rental.get('has_agreement') else 'Rent agreement document was not uploaded.')
    story.append(Paragraph(f'\u2022 {agree_txt}', ParagraphStyle(
        'ag', fontName=_PDF_FONT, fontSize=8.2, leading=11, textColor=_PDF_MUTED)))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    buf.seek(0)
    return buf


def _save_upload(storage, allowed_ext):
    """Persist an uploaded file into static/uploads. Returns (relpath, error)."""
    if storage is None or not storage.filename:
        return None, None
    ext = storage.filename.rsplit('.', 1)[-1].lower() if '.' in storage.filename else ''
    if ext not in allowed_ext:
        return None, 'Allowed types: ' + ', '.join(sorted(allowed_ext)).upper()
    storage.seek(0, os.SEEK_END)
    size = storage.tell()
    storage.seek(0)
    if size > 5 * 1024 * 1024:
        return None, 'File exceeds the 5 MB limit.'
    safe_name = uuid.uuid4().hex + '.' + ext
    storage.save(os.path.join(UPLOAD_FOLDER, safe_name))
    return f'uploads/{safe_name}', None


def _remove_upload(rel_path):
    if not rel_path:
        return
    full = os.path.join(app.static_folder, rel_path)
    try:
        if os.path.exists(full):
            os.remove(full)
    except OSError:
        pass


def _role_map():
    """typename -> usertype id, resolved once per request."""
    if not hasattr(g, '_role_map'):
        conn = None
        mapping = {}
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT id, typename FROM usertype')
            mapping = {r['typename']: r['id'] for r in cursor.fetchall()}
            cursor.close()
        except Exception:
            app.logger.exception('role map failed')
        finally:
            if conn:
                conn.close()
        g._role_map = mapping
    return g._role_map


def _rid(name):
    return _role_map().get(name)


def _require_roles(*role_names):
    if 'user_id' not in session:
        return jsonify(success=False, message='Session expired. Please login again.'), 401
    allowed = {_rid(n) for n in role_names} - {None}
    if _get_current_user_type() not in allowed:
        return jsonify(success=False,
                       message='You do not have permission to perform this action.'), 403
    return None


def _require_master_admin():
    return _require_roles('Master Admin')


def _require_admin_level():
    """Master Admin + Admin: everything except the Add User / registration feature."""
    return _require_roles('Master Admin', 'Admin')


def _require_rental_edit():
    """Rental tenants & payments add/update (never delete): Master Admin, Admin, Users."""
    return _require_roles('Master Admin', 'Admin', 'Users')


def _require_rental_delete():
    """Rental payment delete: Master Admin, Room Renter only."""
    return _require_roles('Master Admin', 'Room Renter')


def _user_owns_rental(cursor, rental_id):
    if rental_id is None:
        return False
    cursor.execute('SELECT 1 FROM rentaldetails WHERE id = %s AND userid = %s LIMIT 1',
                   (rental_id, session['user_id']))
    return cursor.fetchone() is not None


def _driver_belongs_to_user(cursor, driver_id):
    if driver_id is None:
        return False
    cursor.execute('SELECT 1 FROM drivers WHERE id = %s AND userid = %s LIMIT 1',
                   (driver_id, session['user_id']))
    return cursor.fetchone() is not None


def _load_rental_overview(filter_year=None):
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()

        me = session.get('user_id')
        is_renter = 'user_id' in session and _get_current_user_type() == _rid('Room Renter')
        owner_sql = 'AND r.userid = %s' if is_renter else ''
        owner_params = (me,) if is_renter else ()

        year_join = ''
        year_params = ()
        if filter_year and filter_year.isdigit():
            year_join = 'AND rd.year = %s'
            year_params = (int(filter_year),)

        cursor.execute(f"""
            SELECT r.id, r.userid, r.usertypeid, ut.typename AS type_name,
                   u.firstname, u.lastname, u.email, u.phone,
                   r.aadharno, r.panno, r.floortype, r.aadhar_address, r.occupation,
                   r.total_member, r.rental_joiningdate, r.created_at,
                   r.rentagrement, r.aadharimage, r.panimage, r.rentalimage,
                   COALESCE(pay.total_paid, 0)::float AS total_paid,
                   COALESCE(pay.months_paid, 0) AS months_paid
            FROM rentaldetails r
            JOIN users u ON u.id = r.userid
            LEFT JOIN usertype ut ON ut.id = r.usertypeid
            LEFT JOIN (
                SELECT rentalid, SUM(rentamount) AS total_paid, COUNT(*) AS months_paid
                FROM rentdetails GROUP BY rentalid
            ) pay ON pay.rentalid = r.id
            WHERE TRUE {owner_sql}
            ORDER BY r.created_at DESC
        """, owner_params)
        rentals = cursor.fetchall()

        cursor.execute(f"""
            SELECT rd.id, rd.year, rd.month, rd.rentamount::float AS rentamount, rd.currentdate, rd.rentalid,
                   u.firstname, u.lastname, r.aadharno, r.floortype
            FROM rentdetails rd
            JOIN rentaldetails r ON r.id = rd.rentalid
            JOIN users u ON u.id = r.userid
            WHERE TRUE {owner_sql} {'AND rd.year = %s' if year_params else ''}
            ORDER BY rd.currentdate DESC, rd.id DESC
        """, owner_params + year_params)
        ledger = cursor.fetchall()

        now_y, now_m = date.today().year, date.today().month
        cursor.execute(f"""
            SELECT
              (SELECT COUNT(*) FROM rentaldetails r WHERE TRUE {owner_sql}) AS tenants,
              (SELECT COALESCE(SUM(total_member), 0) FROM rentaldetails r WHERE TRUE {owner_sql}) AS members,
              (SELECT COALESCE(SUM(rd.rentamount), 0)::float FROM rentdetails rd
                  JOIN rentaldetails r ON r.id = rd.rentalid
                  WHERE EXTRACT(YEAR FROM rd.currentdate) = %s {owner_sql}) AS collected_year,
              (SELECT COALESCE(SUM(rd.rentamount), 0)::float FROM rentdetails rd
                  JOIN rentaldetails r ON r.id = rd.rentalid
                  WHERE EXTRACT(YEAR FROM rd.currentdate) = %s
                    AND EXTRACT(MONTH FROM rd.currentdate) = %s {owner_sql}) AS collected_month,
              (SELECT COALESCE(SUM(rd.rentamount), 0)::float FROM rentdetails rd
                  JOIN rentaldetails r ON r.id = rd.rentalid
                  WHERE TRUE {owner_sql}) AS collected_all
        """, owner_params + owner_params + (now_y,) + owner_params + (now_y, now_m) + owner_params + owner_params)
        stats = cursor.fetchone()

        cursor.execute(f"""
            SELECT DISTINCT rd.year FROM rentdetails rd
            JOIN rentaldetails r ON r.id = rd.rentalid
            WHERE TRUE {owner_sql}
            ORDER BY rd.year DESC
        """, owner_params)
        years = [row['year'] for row in cursor.fetchall()]
        if now_y not in years:
            years.insert(0, now_y)

        if is_renter:
            choices = []
        else:
            cursor.execute("""
                SELECT u.id, u.firstname, u.lastname, u.email, ut.typename AS type_name
                FROM users u
                JOIN usertype ut ON ut.id = u.istype
                WHERE u.isactive = TRUE
                  AND ut.id = 4
                  AND NOT EXISTS (SELECT 1 FROM rentaldetails r WHERE r.userid = u.id)
                ORDER BY u.firstname
            """)
            choices = cursor.fetchall()

        cursor.close()
        return {'rentals': rentals, 'ledger': ledger, 'stats': stats,
                'years': years, 'choices': choices}
    except Exception:
        app.logger.exception('rental overview failed')
        return {'rentals': [], 'ledger': [], 'stats': None, 'years': [], 'choices': []}
    finally:
        if conn:
            conn.close()


@app.route('/rental-management')
def rental_management():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if _get_current_user_type() == _rid('Driver'):
        flash('Rides team members can manage their work from the Rides Management page.', 'info')
        return redirect(url_for('rides_management'))

    filter_year = request.args.get('year', '')
    data = _load_rental_overview(filter_year)
    me_type = _get_current_user_type()

    return render_template('RentalMangmt.html',
                           rentals=data['rentals'], ledger=data['ledger'],
                           stats=data['stats'], years=data['years'],
                           choices=data['choices'], filter_year=filter_year,
                           me_type=me_type, me_type_name=_get_current_user_type_name())


@app.route('/rental/create', methods=['POST'])
def create_rental():
    guard = _require_rental_edit()
    if guard:
        return guard

    userid = request.form.get('userid', '').strip()
    aadharno = request.form.get('aadharno', '').strip()
    panno = request.form.get('panno', '').strip().upper()
    floortype = request.form.get('floortype', '').strip()
    occupation = request.form.get('occupation', '').strip()
    total_member = request.form.get('total_member', '').strip()
    joiningdate = request.form.get('rental_joiningdate', '').strip()
    address = request.form.get('aadhar_address', '').strip()

    errors = {}

    if not userid or not userid.isdigit():
        errors['userid'] = 'Please select a tenant.'
    if not _aadhar_re.match(aadharno):
        errors['aadharno'] = 'Aadhaar number must be exactly 12 digits.'
    if panno and not _pan_re.match(panno):
        errors['panno'] = 'PAN format must be ABCDE1234F.'
    if not total_member or not total_member.isdigit() or int(total_member) < 1:
        errors['total_member'] = 'Total members must be at least 1.'

    join_date = None
    if not joiningdate:
        errors['rental_joiningdate'] = 'Joining date is required.'
    else:
        try:
            join_date = datetime.strptime(joiningdate, '%Y-%m-%d').date()
        except ValueError:
            errors['rental_joiningdate'] = 'Enter a valid date.'

    agreement_path, err_agree = _save_upload(request.files.get('rentagrement'), _ALLOWED_PDF_EXT)
    if err_agree:
        errors['rentagrement'] = 'Rent agreement must be a PDF file (max 5 MB).'
    aadhar_img_path, err_ai = _save_upload(request.files.get('aadharimage'), _ALLOWED_IMG_EXT)
    if err_ai:
        errors['aadharimage'] = 'Aadhaar image must be PNG/JPG/WEBP (max 5 MB).'
    pan_img_path, err_pi = _save_upload(request.files.get('panimage'), _ALLOWED_IMG_EXT)
    if err_pi:
        errors['panimage'] = 'PAN image must be PNG/JPG/WEBP (max 5 MB).'
    rental_img_path, err_ri = _save_upload(request.files.get('rentalimage'), _ALLOWED_IMG_EXT)
    if err_ri:
        errors['rentalimage'] = 'Rental image must be PNG/JPG/WEBP (max 5 MB).'

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()

        if 'userid' not in errors:
            cursor.execute("""
                SELECT u.id, u.isactive FROM users u WHERE u.id = %s LIMIT 1
            """, (int(userid),))
            target = cursor.fetchone()
            if not target:
                errors['userid'] = 'Selected user does not exist.'
            elif not target['isactive']:
                errors['userid'] = 'Selected user is inactive.'
            else:
                cursor.execute('SELECT 1 FROM rentaldetails WHERE userid = %s LIMIT 1', (int(userid),))
                if cursor.fetchone():
                    errors['userid'] = 'This user already has a rental record.'

        if 'aadharno' not in errors:
            cursor.execute('SELECT 1 FROM rentaldetails WHERE aadharno = %s LIMIT 1', (aadharno,))
            if cursor.fetchone():
                errors['aadharno'] = 'This Aadhaar number is already registered.'

        if errors:
            cursor.close()
            return jsonify(success=False, message='Please fix the highlighted fields.', errors=errors), 400

        cursor.execute('SELECT istype FROM users WHERE id = %s', (int(userid),))
        usertypeid = cursor.fetchone()['istype']

        cursor.execute("""
            INSERT INTO rentaldetails
                (userid, usertypeid, aadharno, rentagrement, panno, aadharimage, panimage,
                 floortype, aadhar_address, occupation, total_member, rentalimage, rental_joiningdate)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (int(userid), usertypeid, aadharno, agreement_path, panno or None,
              aadhar_img_path, pan_img_path, floortype or None, address or None,
              occupation or None, int(total_member), rental_img_path, join_date))
        conn.commit()
        cursor.close()
        return jsonify(success=True, message='Tenant added successfully.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        app.logger.exception('create_rental failed')
        return jsonify(success=False, message='Could not save the tenant. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/rental/payment/add', methods=['POST'])
def add_rent_payment():
    if 'user_id' not in session:
        return jsonify(success=False, message='Session expired. Please login again.'), 401

    rentalid = request.form.get('rentalid', '').strip()

    # Room Renters may record payments for their OWN tenancy only.
    if _get_current_user_type() == _rid('Room Renter'):
        conn = None
        owns = False
        try:
            conn = get_db()
            cursor = conn.cursor()
            owns = _user_owns_rental(cursor, int(rentalid) if rentalid.isdigit() else None)
            cursor.close()
        except Exception:
            pass
        finally:
            if conn:
                conn.close()
        if not owns:
            return jsonify(success=False,
                           message='You can only add rent for your own tenancy.'), 403
    else:
        guard = _require_rental_edit()
        if guard:
            return guard

    year = request.form.get('year', '').strip()
    month = request.form.get('month', '').strip()
    amount = request.form.get('rentamount', '').strip()

    errors = {}
    if not rentalid or not rentalid.isdigit():
        errors['rentalid'] = 'Invalid tenant selected.'
    try:
        yr = int(year)
        if yr < 2000 or yr > 2100:
            raise ValueError
    except (TypeError, ValueError):
        errors['year'] = 'Enter a valid year.'
        yr = None
    if not month or not month.isdigit() or not (1 <= int(month) <= 12):
        errors['month'] = 'Please select the rent month.'
        m = None
    else:
        m = int(month)
    try:
        amt = round(float(amount), 2)
        if amt <= 0 or amt > 10000000:
            raise ValueError
    except (TypeError, ValueError):
        errors['rentamount'] = 'Enter a valid amount greater than 0.'

    if errors:
        return jsonify(success=False, message='Please fix the highlighted fields.', errors=errors), 400

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM rentaldetails WHERE id = %s LIMIT 1', (int(rentalid),))
        if not cursor.fetchone():
            cursor.close()
            return jsonify(success=False, message='Tenant record not found.',
                           errors={'rentalid': 'Tenant record not found.'}), 400

        cursor.execute("""
            SELECT id FROM rentdetails
            WHERE rentalid = %s AND year = %s AND month = %s LIMIT 1
        """, (int(rentalid), yr, m))
        if cursor.fetchone():
            cursor.close()
            return jsonify(success=False,
                           message=f'Rent for {_MONTH_NAMES[m - 1]} {yr} is already recorded.',
                           errors={'month': f'{_MONTH_NAMES[m - 1]} {yr} already has a payment.'}), 400

        cursor.execute(
            'INSERT INTO rentdetails (year, month, rentamount, rentalid) VALUES (%s, %s, %s, %s)',
            (yr, m, amt, int(rentalid)))
        conn.commit()
        cursor.close()
        return jsonify(success=True,
                       message=f'Rent of â‚¹{amt:,.2f} for {_MONTH_NAMES[m - 1]} {yr} recorded successfully.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        app.logger.exception('add_rent_payment failed')
        return jsonify(success=False, message='Could not record the payment. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/rental/payments/<int:rental_id>')
def rental_payments(rental_id):
    if 'user_id' not in session:
        return jsonify(success=False, message='Session expired. Please login again.'), 401

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.aadharno, r.panno, r.floortype, r.occupation, r.total_member,
                   r.aadhar_address, r.rental_joiningdate,
                   r.rentagrement, r.aadharimage, r.panimage, r.rentalimage,
                   u.firstname, u.lastname, ut.typename AS type_name
            FROM rentaldetails r
            JOIN users u ON u.id = r.userid
            LEFT JOIN usertype ut ON ut.id = r.usertypeid
            WHERE r.id = %s LIMIT 1
        """, (rental_id,))
        tenant = cursor.fetchone()
        if not tenant:
            cursor.close()
            return jsonify(success=False, message='Tenant not found.'), 404
        if tenant['rental_joiningdate']:
            tenant['joined_label'] = tenant['rental_joiningdate'].strftime('%d %b %Y')

        cursor.execute("""
            SELECT id, year, month, rentamount::float AS rentamount, currentdate,
                   last_updated_at, last_update_note
            FROM rentdetails WHERE rentalid = %s
            ORDER BY year DESC, month DESC, currentdate DESC
        """, (rental_id,))
        payments = cursor.fetchall()
        for p in payments:
            p['paid_on'] = p['currentdate'].strftime('%d %b %Y, %I:%M %p')
            p['updated_on'] = (p['last_updated_at'].strftime('%d %b %Y, %I:%M %p')
                               if p['last_updated_at'] else '')
            p['update_note'] = p['last_update_note'] or ''
        cursor.close()
        return jsonify(success=True, tenant=tenant, payments=payments)
    except Exception:
        app.logger.exception('rental_payments failed')
        return jsonify(success=False, message='Could not load payment history.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/rental/download/<int:rental_id>')
def rental_download_pdf(rental_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    denied = _require_admin_level()
    if denied:
        return denied

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.*, u.firstname, u.lastname, u.email, u.phone,
                   ut.typename AS type_name
            FROM rentaldetails r
            JOIN users u ON u.id = r.userid
            LEFT JOIN usertype ut ON ut.id = r.usertypeid
            WHERE r.id = %s LIMIT 1
        """, (rental_id,))
        r = cursor.fetchone()
        if not r:
            cursor.close()
            flash('Rental record not found.', 'danger')
            return redirect(url_for('rental_management'))

        cursor.execute("""
            SELECT id, year, month, rentamount::float AS rentamount, currentdate,
                   last_updated_at, last_update_note
            FROM rentdetails WHERE rentalid = %s
            ORDER BY year ASC, month ASC, currentdate ASC
        """, (rental_id,))
        payments = cursor.fetchall()
        cursor.close()

        safe_name = re.sub(r'[^A-Za-z0-9]+', '_', f"{r['firstname']}_{r['lastname']}").strip('_') or 'Tenant'
        rental_ctx = {
            'id': r['id'],
            'safe_name': safe_name,
            'full_name': f"{r['firstname']} {r['lastname']}",
            'email': r['email'], 'phone': r['phone'],
            'aadharno': r['aadharno'], 'panno': r['panno'] or '-',
            'floortype': r['floortype'] or '-', 'occupation': r['occupation'] or '-',
            'total_member': r['total_member'], 'aadhar_address': r['aadhar_address'] or '-',
            'joining_label': (r['rental_joiningdate'].strftime('%d %b %Y')
                              if r['rental_joiningdate'] else '-'),
            'type_name': r['type_name'],
            'aadharimage': r['aadharimage'], 'panimage': r['panimage'], 'rentalimage': r['rentalimage'],
            'has_agreement': bool(r['rentagrement']),
        }
        pay_ctx = [{
            'id': p['id'], 'year': p['year'], 'month': p['month'],
            'rentamount': float(p['rentamount'] or 0),
            'added_on': (p['currentdate'].strftime('%d %b %Y, %I:%M %p')
                         if p['currentdate'] else '-'),
            'updated_on': (p['last_updated_at'].strftime('%d %b %Y, %I:%M %p')
                           if p['last_updated_at'] else ''),
            'update_note': p['last_update_note'] or '',
        } for p in payments]

        pdf_buf = _build_rental_pdf(rental_ctx, pay_ctx)

        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f'{safe_name}_Rental_Report.pdf', pdf_buf.read())
            for col, label in (('aadharimage', 'Aadhaar'), ('panimage', 'PAN'),
                               ('rentagrement', 'Rent_Agreement')):
                rel = r[col]
                if not rel:
                    continue
                fp = os.path.join(app.static_folder, rel)
                if os.path.exists(fp):
                    ext = rel.rsplit('.', 1)[-1].lower()
                    zf.write(fp, f'{label}_{safe_name}.{ext}')

        zbuf.seek(0)
        return send_file(zbuf, mimetype='application/zip', as_attachment=True,
                         download_name=f'{safe_name}_Rental_Documents.zip')
    except Exception:
        app.logger.exception('rental_download_pdf failed')
        flash('Could not generate the download package.', 'danger')
        return redirect(url_for('rental_management'))
    finally:
        if conn:
            conn.close()


@app.route('/rental/update', methods=['POST'])
def update_rental():
    denied = _require_rental_edit()
    if denied:
        return denied

    rental_id = request.form.get('rental_id', '').strip()
    aadharno = request.form.get('aadharno', '').strip()
    panno = request.form.get('panno', '').strip().upper()
    floortype = request.form.get('floortype', '').strip()
    occupation = request.form.get('occupation', '').strip()
    total_member = request.form.get('total_member', '').strip()
    joiningdate = request.form.get('rental_joiningdate', '').strip()
    address = request.form.get('aadhar_address', '').strip()

    errors = {}

    if not rental_id or not rental_id.isdigit():
        errors['rental_id'] = 'Invalid rental record.'
    if not _aadhar_re.match(aadharno):
        errors['aadharno'] = 'Aadhaar number must be exactly 12 digits.'
    if panno and not _pan_re.match(panno):
        errors['panno'] = 'PAN format must be ABCDE1234F.'
    if not total_member or not total_member.isdigit() or int(total_member) < 1:
        errors['total_member'] = 'Total members must be at least 1.'

    join_date = None
    if not joiningdate:
        errors['rental_joiningdate'] = 'Joining date is required.'
    else:
        try:
            join_date = datetime.strptime(joiningdate, '%Y-%m-%d').date()
        except ValueError:
            errors['rental_joiningdate'] = 'Enter a valid date.'

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()

        existing = None
        if not errors or 'rental_id' not in errors:
            cursor.execute("SELECT * FROM rentaldetails WHERE id = %s LIMIT 1", (int(rental_id),))
            existing = cursor.fetchone()
            if not existing:
                errors['rental_id'] = 'Rental record not found.'

        if existing and 'aadharno' not in errors:
            cursor.execute("""
                SELECT id FROM rentaldetails WHERE aadharno = %s AND id <> %s LIMIT 1
            """, (aadharno, int(rental_id)))
            if cursor.fetchone():
                errors['aadharno'] = 'This Aadhaar number is already registered.'

        agreement_path, err_agree = _save_upload(request.files.get('rentagrement'), _ALLOWED_PDF_EXT)
        if err_agree:
            errors['rentagrement'] = err_agree
        aadhar_img_path, err_ai = _save_upload(request.files.get('aadharimage'), _ALLOWED_IMG_EXT)
        if err_ai:
            errors['aadharimage'] = err_ai
        pan_img_path, err_pi = _save_upload(request.files.get('panimage'), _ALLOWED_IMG_EXT)
        if err_pi:
            errors['panimage'] = err_pi
        rental_img_path, err_ri = _save_upload(request.files.get('rentalimage'), _ALLOWED_IMG_EXT)
        if err_ri:
            errors['rentalimage'] = err_ri

        if errors:
            for new_path in (agreement_path, aadhar_img_path, pan_img_path, rental_img_path):
                _remove_upload(new_path)
            cursor.close()
            return jsonify(success=False, message='Please fix the highlighted fields.', errors=errors), 400

        final_paths = {
            'rentagrement': agreement_path or existing['rentagrement'],
            'aadharimage': aadhar_img_path or existing['aadharimage'],
            'panimage': pan_img_path or existing['panimage'],
            'rentalimage': rental_img_path or existing['rentalimage'],
        }

        cursor.execute("""
            UPDATE rentaldetails SET
                aadharno = %s, panno = %s, floortype = %s, occupation = %s,
                total_member = %s, aadhar_address = %s, rental_joiningdate = %s,
                rentagrement = %s, aadharimage = %s, panimage = %s, rentalimage = %s
            WHERE id = %s
        """, (aadharno, panno or None, floortype or None, occupation or None,
              int(total_member), address or None, join_date,
              final_paths['rentagrement'], final_paths['aadharimage'],
              final_paths['panimage'], final_paths['rentalimage'], int(rental_id)))
        conn.commit()
        cursor.close()

        for col, new_path in final_paths.items():
            if new_path != existing[col]:
                _remove_upload(existing[col])

        return jsonify(success=True, message='Tenant details updated successfully.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        app.logger.exception('update_rental failed')
        return jsonify(success=False, message='Could not update the tenant. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/rental/payment/update', methods=['POST'])
def update_rent_payment():
    denied = _require_rental_edit()
    if denied:
        return denied

    payment_id = request.form.get('payment_id', '').strip()
    year = request.form.get('year', '').strip()
    month = request.form.get('month', '').strip()
    amount = request.form.get('rentamount', '').strip()

    errors = {}
    if not payment_id or not payment_id.isdigit():
        errors['payment_id'] = 'Invalid payment record.'
    try:
        yr = int(year)
        if yr < 2000 or yr > 2100:
            raise ValueError
    except (TypeError, ValueError):
        errors['year'] = 'Enter a valid year.'
        yr = None
    if not month or not month.isdigit() or not (1 <= int(month) <= 12):
        errors['month'] = 'Please select the rent month.'
        m = None
    else:
        m = int(month)
    try:
        amt = round(float(amount), 2)
        if amt <= 0 or amt > 10000000:
            raise ValueError
    except (TypeError, ValueError):
        errors['rentamount'] = 'Enter a valid amount greater than 0.'

    if errors:
        return jsonify(success=False, message='Please fix the highlighted fields.', errors=errors), 400

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT rd.id, rd.rentalid, rd.year, rd.month, rd.rentamount::float AS rentamount
            FROM rentdetails rd WHERE rd.id = %s LIMIT 1
        """, (int(payment_id),))
        payment = cursor.fetchone()
        if not payment:
            cursor.close()
            return jsonify(success=False, message='Payment record not found.',
                           errors={'payment_id': 'Payment record not found.'}), 404

        cursor.execute("""
            SELECT id FROM rentdetails
            WHERE rentalid = %s AND year = %s AND month = %s AND id <> %s LIMIT 1
        """, (payment['rentalid'], yr, m, int(payment_id)))
        if cursor.fetchone():
            cursor.close()
            return jsonify(success=False,
                           message=f'Rent for {_MONTH_NAMES[m - 1]} {yr} is already recorded for this tenant.',
                           errors={'month': f'{_MONTH_NAMES[m - 1]} {yr} already has another payment.'}), 400

        old_label = (f"{_MONTH_NAMES[(payment['month'] or 1) - 1]} {payment['year']}, "
                     f"\u20b9{float(payment['rentamount']):,.2f}")
        new_label = f"{_MONTH_NAMES[m - 1]} {yr}, \u20b9{amt:,.2f}"
        cursor.execute("""
            UPDATE rentdetails
            SET year = %s, month = %s, rentamount = %s,
                last_updated_at = CURRENT_TIMESTAMP,
                last_update_note = %s
            WHERE id = %s
        """, (yr, m, amt, f'{old_label} \u2192 {new_label}', int(payment_id)))
        conn.commit()
        cursor.close()
        return jsonify(success=True,
                       message=f'Payment corrected to {_MONTH_NAMES[m - 1]} {yr}, â‚¹{amt:,.2f}.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        app.logger.exception('update_rent_payment failed')
        return jsonify(success=False, message='Could not update the payment. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/rental/payment/delete', methods=['POST'])
def delete_rent_payment():
    denied = _require_rental_delete()
    if denied:
        return denied

    payment_id = request.form.get('payment_id', '').strip()
    if not payment_id or not payment_id.isdigit():
        return jsonify(success=False, message='Invalid payment record.'), 400

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT rd.id, rd.year, rd.month, rd.rentamount::float AS rentamount
            FROM rentdetails rd WHERE rd.id = %s LIMIT 1
        """, (int(payment_id),))
        payment = cursor.fetchone()
        if not payment:
            cursor.close()
            return jsonify(success=False, message='Payment record not found.'), 404

        period = f"{_MONTH_NAMES[(payment['month'] or 1) - 1]} {payment['year']}"
        amount_label = f"\u20b9{float(payment['rentamount']):,.2f}"
        cursor.execute('DELETE FROM rentdetails WHERE id = %s', (int(payment_id),))
        conn.commit()
        cursor.close()
        return jsonify(success=True,
                       message=f'Payment for {period}, {amount_label} deleted successfully.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        app.logger.exception('delete_rent_payment failed')
        return jsonify(success=False, message='Could not delete the payment. Please try again.'), 500
    finally:
        if conn:
            conn.close()


def _validate_finance_form(form, types_by_id, banks_set):
    errors = {}
    type_raw = form.get('category', '').strip()
    bank = form.get('bank_name', '').strip()
    user_id = form.get('fin_user', '').strip()
    remarks = form.get('remarks', '').strip()
    date_str = form.get('entry_date', '').strip()
    fd_no = re.sub(r'\s+', ' ', form.get('fd_no', '').strip()).strip()

    type_id = None
    type_name = ''
    if not type_raw.isdigit() or int(type_raw) not in types_by_id:
        errors['category'] = 'Please choose a valid managed amount type.'
    else:
        type_id = int(type_raw)
        type_name = types_by_id[type_id]

    amount_raw = form.get('amount', '').strip().replace(',', '')
    try:
        amount = round(float(amount_raw), 2)
        if amount <= 0 or amount > 9999999999:
            raise ValueError
    except (TypeError, ValueError):
        amount = None
        errors['amount'] = 'Enter a valid amount greater than 0.'

    if not bank:
        errors['bank_name'] = 'Bank is required.'
    elif bank not in banks_set:
        errors['bank_name'] = 'Select a bank from the list.'

    uid = None
    if not user_id or not user_id.isdigit():
        errors['fin_user'] = 'Select the user account.'
    else:
        uid = int(user_id)

    if type_name == 'Others' and len(remarks) < 3:
        errors['remarks'] = 'Remarks are required when the type is Others.'
    elif len(remarks) > 500:
        errors['remarks'] = 'Remarks must be within 500 characters.'

    if len(fd_no) > 40:
        errors['fd_no'] = 'FD No must be within 40 characters.'
    elif type_name == 'Fixed Deposit' and len(fd_no) < 2:
        errors['fd_no'] = 'FD No is required when the type is Fixed Deposit.'

    entry_date = None
    if date_str:
        try:
            entry_date = date.fromisoformat(date_str)
        except ValueError:
            errors['entry_date'] = 'Enter a valid date.'

    return errors, {'type_id': type_id, 'type_name': type_name, 'amount': amount,
                    'bank': bank, 'uid': uid, 'remarks': remarks, 'date': entry_date,
                    'fd_no': fd_no}


def _load_finance_overview(filter_type='', filter_bank=''):
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute('SELECT id, type_name FROM finance_type_master WHERE isactive = TRUE ORDER BY id')
        fin_types = cursor.fetchall()
        cursor.execute('SELECT id, bank_name FROM bank_master WHERE isactive = TRUE ORDER BY bank_name')
        fin_banks = [{'id': r['id'], 'bank_name': r['bank_name']} for r in cursor.fetchall()]

        bank_names = [b['bank_name'] for b in fin_banks]
        conditions, params = [], []
        if filter_type.isdigit() and any(t['id'] == int(filter_type) for t in fin_types):
            conditions.append('fe.type_id = %s')
            params.append(int(filter_type))
        if filter_bank and filter_bank in bank_names:
            conditions.append('fe.bank_name = %s')
            params.append(filter_bank)
        where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''

        cursor.execute(f"""
            SELECT fe.id, fe.type_id, tm.type_name,
                   fe.amount::float AS amount, fe.bank_name, fe.fd_no,
                   fe.user_id, u.firstname, u.lastname, u.email,
                   fe.remarks, fe.entry_date, fe.created_at, fe.updated_at
            FROM finance_entries fe
            JOIN finance_type_master tm ON tm.id = fe.type_id
            LEFT JOIN users u ON u.id = fe.user_id
            {where}
            ORDER BY fe.entry_date DESC, fe.id DESC
        """, tuple(params) if params else None)
        entries = cursor.fetchall()

        cursor.execute("""
            SELECT
              (SELECT COALESCE(SUM(rentamount), 0)::float FROM rentdetails) AS total_rental,
              (SELECT COALESCE(SUM(amount), 0)::float FROM finance_entries) AS managed
        """)
        totals = cursor.fetchone()
        totals['unmanaged'] = round(max((totals['total_rental'] or 0) - (totals['managed'] or 0), 0.0), 2)

        cursor.execute("""
            SELECT u.id, u.firstname, u.lastname, u.email
            FROM users u
            JOIN usertype ut ON ut.id = u.istype
            WHERE u.isactive = TRUE AND ut.id IN (1, 2)
            ORDER BY u.firstname
        """)
        users_list = cursor.fetchall()

        cursor.close()
        return {'entries': entries, 'totals': totals, 'users': users_list,
                'types': fin_types, 'banks': fin_banks}
    except Exception:
        app.logger.exception('finance overview failed')
        return {'entries': [],
                'totals': {'total_rental': 0, 'managed': 0, 'unmanaged': 0},
                'users': [], 'types': [], 'banks': []}
    finally:
        if conn:
            conn.close()


@app.route('/finance-management')
def finance_management():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    me_t = _get_current_user_type()
    if me_t not in (_rid('Master Admin'), _rid('Admin'), _rid('Users')):
        if me_t == _rid('Driver'):
            return redirect(url_for('rides_management'))
        return redirect(url_for('rental_management'))

    filter_type = request.args.get('type', '')
    filter_bank = request.args.get('bank', '')
    data = _load_finance_overview(filter_type, filter_bank)

    return render_template('finance_management.html',
                           entries=data['entries'], totals=data['totals'],
                           users=data['users'], types=data['types'], banks=data['banks'],
                           today=date.today().isoformat(),
                           filter_type=filter_type, filter_bank=filter_bank,
                           me_type=_get_current_user_type(),
                           me_type_name=_get_current_user_type_name())


def _finance_user_exists(cursor, uid):
    cursor.execute('SELECT 1 FROM users WHERE id = %s LIMIT 1', (uid,))
    return cursor.fetchone() is not None


def _finance_master_sets(cursor):
    cursor.execute('SELECT id, type_name FROM finance_type_master WHERE isactive = TRUE')
    types_by_id = {r['id']: r['type_name'] for r in cursor.fetchall()}
    cursor.execute('SELECT bank_name FROM bank_master WHERE isactive = TRUE')
    banks_set = {r['bank_name'] for r in cursor.fetchall()}
    return types_by_id, banks_set


def _finance_unmanaged_left(cursor, exclude_id=None):
    """How much of the total rental amount is still unmanaged (>= 0)."""
    cursor.execute('SELECT COALESCE(SUM(rentamount), 0)::float AS total FROM rentdetails')
    total = cursor.fetchone()['total'] or 0
    if exclude_id:
        cursor.execute('SELECT COALESCE(SUM(amount), 0)::float AS managed FROM finance_entries WHERE id <> %s',
                       (exclude_id,))
    else:
        cursor.execute('SELECT COALESCE(SUM(amount), 0)::float AS managed FROM finance_entries')
    managed = cursor.fetchone()['managed'] or 0
    return round(total - managed, 2)


@app.route('/finance/create', methods=['POST'])
def finance_create():
    guard = _require_admin_level()
    if guard:
        return guard

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        types_by_id, banks_set = _finance_master_sets(cursor)
        errors, v = _validate_finance_form(request.form, types_by_id, banks_set)

        if not errors and v['uid'] is not None and not _finance_user_exists(cursor, v['uid']):
            errors['fin_user'] = 'Selected user account no longer exists.'
        if not errors and v['amount'] is not None:
            available = _finance_unmanaged_left(cursor)
            if v['amount'] > available + 1e-9:
                errors['amount'] = (f'Amount exceeds the unmanaged balance (\u20b9{available:,.2f} left). '
                                    f'Managed amount can never be more than the Total Rental Amount.')
        if errors:
            cursor.close()
            return jsonify(success=False, message='Please fix the highlighted fields.', errors=errors), 400

        cursor.execute("""
            INSERT INTO finance_entries (type_id, amount, bank_name, fd_no, user_id, remarks, entry_date)
            VALUES (%s, %s, %s, NULLIF(%s, ''), %s, NULLIF(%s, ''), COALESCE(%s, CURRENT_DATE))
        """, (v['type_id'], v['amount'], v['bank'], v['fd_no'], v['uid'], v['remarks'], v['date']))
        conn.commit()
        cursor.close()
        return jsonify(success=True,
                       message=f'{v["type_name"]} of \u20b9{v["amount"]:,.2f} recorded successfully.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        app.logger.exception('finance_create failed')
        return jsonify(success=False, message='Could not save the entry. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/finance/update', methods=['POST'])
def finance_update():
    guard = _require_admin_level()
    if guard:
        return guard

    entry_id = request.form.get('id', '').strip()
    if not entry_id.isdigit():
        return jsonify(success=False, message='Invalid entry.'), 400

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id, amount::float AS amount FROM finance_entries WHERE id = %s LIMIT 1',
                       (int(entry_id),))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return jsonify(success=False, message='Entry not found.'), 404

        types_by_id, banks_set = _finance_master_sets(cursor)
        errors, v = _validate_finance_form(request.form, types_by_id, banks_set)

        if not errors and v['uid'] is not None and not _finance_user_exists(cursor, v['uid']):
            errors['fin_user'] = 'Selected user account no longer exists.'
        if not errors and v['amount'] is not None:
            available = _finance_unmanaged_left(cursor, exclude_id=int(entry_id))
            if v['amount'] > available + 1e-9:
                errors['amount'] = (f'Amount exceeds the unmanaged balance (\u20b9{available:,.2f} left). '
                                    f'Managed amount can never be more than the Total Rental Amount.')
        if errors:
            cursor.close()
            return jsonify(success=False, message='Please fix the highlighted fields.', errors=errors), 400

        cursor.execute("""
            UPDATE finance_entries
            SET type_id = %s, amount = %s, bank_name = %s, fd_no = NULLIF(%s, ''), user_id = %s,
                remarks = NULLIF(%s, ''), entry_date = COALESCE(%s, entry_date),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (v['type_id'], v['amount'], v['bank'], v['fd_no'], v['uid'], v['remarks'], v['date'], int(entry_id)))
        conn.commit()
        cursor.close()
        return jsonify(success=True,
                       message=f'Entry updated to {v["type_name"]}, \u20b9{v["amount"]:,.2f}.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        app.logger.exception('finance_update failed')
        return jsonify(success=False, message='Could not update the entry. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/finance/delete', methods=['POST'])
def finance_delete():
    guard = _require_admin_level()
    if guard:
        return guard

    entry_id = request.form.get('id', '').strip()
    if not entry_id.isdigit():
        return jsonify(success=False, message='Invalid entry.'), 400

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM finance_entries WHERE id = %s', (int(entry_id),))
        deleted = cursor.rowcount
        conn.commit()
        cursor.close()
        if not deleted:
            return jsonify(success=False, message='Entry not found.'), 404
        return jsonify(success=True, message='Managed amount entry deleted.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        app.logger.exception('finance_delete failed')
        return jsonify(success=False, message='Could not delete the entry. Please try again.'), 500
    finally:
        if conn:
            conn.close()


def _clean_master_name(raw):
    return re.sub(r'\s+', ' ', (raw or '').strip()).strip()


def _master_unique(cursor, table, column, name, exclude_id=None):
    sql = f'SELECT 1 FROM {table} WHERE LOWER({column}) = LOWER(%s)'
    args = [name]
    if exclude_id:
        sql += ' AND id <> %s'
        args.append(exclude_id)
    cursor.execute(sql + ' LIMIT 1', tuple(args))
    return cursor.fetchone() is None


_FIN_MASTER_TABLES = {
    'type': ('finance_type_master', 'type_name', 'Managed amount type'),
    'bank': ('bank_master', 'bank_name', 'Bank'),
}


@app.route('/finance/master/<kind>/create', methods=['POST'])
def finance_master_create(kind):
    guard = _require_roles('Master Admin', 'Admin', 'Users')
    if guard:
        return guard
    if kind not in _FIN_MASTER_TABLES:
        return jsonify(success=False, message='Unknown master.'), 404
    table, column, label = _FIN_MASTER_TABLES[kind]

    name = _clean_master_name(request.form.get('name', ''))
    max_len = 50 if kind == 'type' else 80
    if len(name) < 2 or len(name) > max_len:
        return jsonify(success=False, message=f'{label} name must be 2-{max_len} characters.',
                       errors={'name': f'Enter 2-{max_len} characters.'}), 400

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        if not _master_unique(cursor, table, column, name):
            cursor.close()
            return jsonify(success=False, message=f'{label} "{name}" already exists.',
                           errors={'name': 'This name already exists.'}), 400
        cursor.execute(f'INSERT INTO {table} ({column}) VALUES (%s) RETURNING id', (name,))
        new_id = cursor.fetchone()['id']
        conn.commit()
        cursor.close()
        return jsonify(success=True, message=f'{label} "{name}" added.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        app.logger.exception('finance_master_create failed')
        return jsonify(success=False, message='Could not save. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/finance/master/<kind>/update', methods=['POST'])
def finance_master_update(kind):
    guard = _require_roles('Master Admin', 'Admin', 'Users')
    if guard:
        return guard
    if kind not in _FIN_MASTER_TABLES:
        return jsonify(success=False, message='Unknown master.'), 404
    table, column, label = _FIN_MASTER_TABLES[kind]

    item_id = request.form.get('id', '').strip()
    if not item_id.isdigit():
        return jsonify(success=False, message='Invalid record.'), 400
    name = _clean_master_name(request.form.get('name', ''))
    max_len = 50 if kind == 'type' else 80
    if len(name) < 2 or len(name) > max_len:
        return jsonify(success=False, message=f'{label} name must be 2-{max_len} characters.',
                       errors={'name': f'Enter 2-{max_len} characters.'}), 400

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        old_row = cursor.execute(f'SELECT {column} AS old_name FROM {table} WHERE id = %s LIMIT 1', (int(item_id),))
        old_row = cursor.fetchone()
        if not old_row:
            cursor.close()
            return jsonify(success=False, message=f'{label} not found.'), 404
        if not _master_unique(cursor, table, column, name, exclude_id=int(item_id)):
            cursor.close()
            return jsonify(success=False, message=f'{label} "{name}" already exists.',
                           errors={'name': 'This name already exists.'}), 400
        cursor.execute(f'UPDATE {table} SET {column} = %s WHERE id = %s', (name, int(item_id)))
        if kind == 'bank':
            cursor.execute('UPDATE finance_entries SET bank_name = %s WHERE bank_name = %s',
                           (name, old_row['old_name']))
            cursor.execute('UPDATE ride_finance_entries SET bank_name = %s WHERE bank_name = %s',
                           (name, old_row['old_name']))
        conn.commit()
        cursor.close()
        return jsonify(success=True, message=f'{label} renamed to "{name}".')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        app.logger.exception('finance_master_update failed')
        return jsonify(success=False, message='Could not update. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/finance/master/<kind>/delete', methods=['POST'])
def finance_master_delete(kind):
    guard = _require_admin_level()
    if guard:
        return guard
    if kind not in _FIN_MASTER_TABLES:
        return jsonify(success=False, message='Unknown master.'), 404
    table, column, label = _FIN_MASTER_TABLES[kind]

    item_id = request.form.get('id', '').strip()
    if not item_id.isdigit():
        return jsonify(success=False, message='Invalid record.'), 400

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(f'SELECT {column} AS name FROM {table} WHERE id = %s LIMIT 1', (int(item_id),))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return jsonify(success=False, message=f'{label} not found.'), 404
        name = row['name']

        if kind == 'type':
            cursor.execute('SELECT COUNT(*) AS n FROM finance_entries WHERE type_id = %s', (int(item_id),))
            fin_used = cursor.fetchone()['n']
            cursor.execute('SELECT COUNT(*) AS n FROM ride_finance_entries WHERE type_id = %s', (int(item_id),))
            ride_used = cursor.fetchone()['n']
            used = fin_used + ride_used
        else:
            cursor.execute('SELECT COUNT(*) AS n FROM finance_entries WHERE bank_name = %s', (name,))
            fin_used = cursor.fetchone()['n']
            cursor.execute('SELECT COUNT(*) AS n FROM ride_finance_entries WHERE bank_name = %s', (name,))
            ride_used = cursor.fetchone()['n']
            used = fin_used + ride_used
        if used:
            cursor.close()
            return jsonify(success=False,
                           message=(f'Cannot delete "{name}": it is used by {used} '
                                    f'entr{"y" if used == 1 else "ies"}. Delete or reassign those first.')), 400

        cursor.execute(f'DELETE FROM {table} WHERE id = %s', (int(item_id),))
        conn.commit()
        cursor.close()
        return jsonify(success=True, message=f'{label} "{name}" deleted.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        app.logger.exception('finance_master_delete failed')
        return jsonify(success=False, message='Could not delete. Please try again.'), 500
    finally:
        if conn:
            conn.close()


_PDF_GREEN = colors.HexColor('#059669')
_PDF_RED = colors.HexColor('#b91c1c')


def _build_finance_pdf(entries, totals, fin_types):
    """Compose a detailed A4 finance management report. Returns BytesIO of PDF bytes."""
    total_amt = float(totals.get('total_rental') or 0)
    managed_amt = float(totals.get('managed') or 0)
    unmanaged_amt = float(totals.get('unmanaged') or 0)
    pct = round(managed_amt / total_amt * 100, 1) if total_amt else 0

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=18 * mm,
                            title='Finance Management Report',
                            author='PDM Finance Management')

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setStrokeColor(_PDF_LINE)
        canvas.setLineWidth(0.7)
        canvas.line(16 * mm, 13 * mm, A4[0] - 16 * mm, 13 * mm)
        canvas.setFont(_PDF_FONT, 7.5)
        canvas.setFillColor(_PDF_MUTED)
        canvas.drawString(16 * mm, 9 * mm, 'PDM \u2022 Finance Management \u2014 system generated document')
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f'Page {doc_.page}')
        canvas.restoreState()

    story = []
    ref = f'FIN-{datetime.now().strftime("%Y%m%d%H%M")}'

    head_left = [
        Paragraph('<font color="#a5b4fc">PDM FINANCE MANAGEMENT</font>',
                  ParagraphStyle('k', fontName=_PDF_FONT_B, fontSize=8, leading=10)),
        Spacer(1, 4),
        Paragraph('<font color="white">Detailed Amount Report</font>',
                  ParagraphStyle('t', fontName=_PDF_FONT_B, fontSize=17, leading=21)),
    ]
    right_style = ParagraphStyle('r', fontName=_PDF_FONT, fontSize=8.5, leading=12, alignment=TA_RIGHT)
    head_right = [
        Paragraph(f'<font color="#c7d2fe">Report Ref</font><br/><font color="white"><b>#{ref}</b></font>', right_style),
        Spacer(1, 3),
        Paragraph(f'<font color="#c7d2fe">Generated</font><br/><font color="white">{datetime.now().strftime("%d %b %Y, %I:%M %p")}</font>', right_style),
    ]
    band = Table([[head_left, head_right]], colWidths=[110 * mm, 68 * mm])
    band.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), _PDF_BAND_BG),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (0, 0), 12),
        ('RIGHTPADDING', (-1, -1), (-1, -1), 12),
        ('LINEBELOW', (0, 0), (-1, -1), 2.5, _PDF_ACCENT),
    ]))
    story += [band, Spacer(1, 8)]

    def sum_cell(label, value_str, fg):
        return [
            Paragraph(f'<font color="#64748b">{label}</font>',
                      ParagraphStyle('sl', fontName=_PDF_FONT_B, fontSize=7.5, leading=10)),
            Spacer(1, 3),
            Paragraph(f'<font color="{fg}"><b>{value_str}</b></font>',
                      ParagraphStyle('sv', fontName=_PDF_FONT_B, fontSize=14, leading=17)),
        ]

    strip = Table([[
        sum_cell('TOTAL RENTAL AMOUNT<br/>(All time rent collected)', _money_str(total_amt), '#0f172a'),
        sum_cell('MANAGED AMOUNT<br/>(Described)', _money_str(managed_amt), '#059669'),
        sum_cell('UNMANAGED AMOUNT<br/>(Not described yet)', _money_str(unmanaged_amt),
                 '#b91c1c' if unmanaged_amt > 0 else '#059669'),
    ]], colWidths=[59.3 * mm, 59.3 * mm, 59.3 * mm])
    strip.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#eef2ff')),
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#ecfdf5')),
        ('BACKGROUND', (2, 0), (2, 0), colors.HexColor('#fef2f2')),
        ('BOX', (0, 0), (0, 0), 0.8, _PDF_LINE),
        ('BOX', (1, 0), (1, 0), 0.8, _PDF_LINE),
        ('BOX', (2, 0), (2, 0), 0.8, _PDF_LINE),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 9),
    ]))
    story += [_pdf_section('AMOUNT SUMMARY'), Spacer(1, 4), strip, Spacer(1, 4)]
    cov_color = '#059669' if unmanaged_amt <= 0.005 else '#b91c1c'
    story.append(Paragraph(
        f'Described coverage: <b>{pct}%</b>. '
        f'Unmanaged Amount = Total Rental \u2212 Managed, and can never go below zero \u2014 '
        f'the system blocks any entry that would exceed the total collected rent.',
        ParagraphStyle('cov', fontName=_PDF_FONT, fontSize=8.5, leading=12, textColor=_PDF_MUTED)))
    story.append(Spacer(1, 10))

    story.append(_pdf_section(f'MANAGED AMOUNT DETAILS ({len(entries)} '
                              f'{"entry" if len(entries) == 1 else "entries"})'))
    story.append(Spacer(1, 4))

    if entries:
        head_row = ['#', 'Type', 'Amount', 'Bank', 'FD No', 'User Account', 'Remarks', 'Date']
        body_rows = []
        for i, e in enumerate(entries, 1):
            holder = (f"{e['firstname']} {e['lastname'] or ''}".strip()) if e['firstname'] else '-'
            rem = e['remarks'] or '-'
            if len(rem) > 60:
                rem = rem[:57] + '...'
            fd = e['fd_no'] or '-'
            if len(fd) > 18:
                fd = fd[:15] + '...'
            body_rows.append([
                str(i), e['type_name'], _money_str(e['amount']), e['bank_name'],
                fd, holder, rem, e['entry_date'].strftime('%d %b %Y') if e['entry_date'] else '-',
            ])
        det = Table([head_row] + body_rows,
                    colWidths=[7 * mm, 22 * mm, 22 * mm, 26 * mm, 18 * mm, 26 * mm, 38 * mm, 19 * mm],
                    repeatRows=1)
        det.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), _PDF_ACCENT_DARK),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), _PDF_FONT_B),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('FONTNAME', (0, 1), (-1, -1), _PDF_FONT),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, _PDF_LINE),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, _PDF_ZEBRA]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story += [det]
    else:
        story.append(Paragraph('No managed entries recorded yet.',
                               ParagraphStyle('em', fontName=_PDF_FONT, fontSize=9, leading=13,
                                              textColor=_PDF_MUTED)))
    story.append(Spacer(1, 10))

    def mini_summary(title, groups, name_head):
        story_ = [_pdf_section(title), Spacer(1, 4)]
        rows_ = [[name_head, 'Entries', 'Total Amount']]
        for nm, cnt, amt in groups:
            rows_.append([nm, str(cnt), _money_str(amt)])
        tot_cnt = sum(g[1] for g in groups)
        tot_amt = sum(g[2] for g in groups)
        rows_.append(['TOTAL', str(tot_cnt), _money_str(tot_amt)])
        t_ = Table(rows_, colWidths=[90 * mm, 30 * mm, 64 * mm])
        t_.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), _PDF_ACCENT_DARK),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), _PDF_FONT_B),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('FONTNAME', (0, 1), (-1, -2), _PDF_FONT),
            ('FONTNAME', (0, -1), (-1, -1), _PDF_FONT_B),
            ('TEXTCOLOR', (0, -1), (-1, -1), _PDF_GREEN),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#ecfdf5')),
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
            ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, _PDF_LINE),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, _PDF_ZEBRA]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story_.append(t_)
        return story_

    type_groups = []
    for t in fin_types:
        trows = [e for e in entries if e['type_name'] == t['type_name']]
        type_groups.append((t['type_name'], len(trows), sum(float(e['amount']) for e in trows)))

    bank_map = {}
    for e in entries:
        k = e['bank_name']
        old = bank_map.get(k, (0, 0.0))
        bank_map[k] = (old[0] + 1, old[1] + float(e['amount']))
    bank_groups = sorted(((k, v[0], v[1]) for k, v in bank_map.items()), key=lambda x: -x[2])

    story += mini_summary('TYPE-WISE SUMMARY', type_groups, 'Managed Amount Type')
    story += [Spacer(1, 8)]
    if bank_groups:
        story += mini_summary('BANK-WISE SUMMARY', bank_groups, 'Bank')
    else:
        story += [_pdf_section('BANK-WISE SUMMARY'), Spacer(1, 4),
                  Paragraph('No banks used yet.', ParagraphStyle(
                      'eb', fontName=_PDF_FONT, fontSize=9, leading=13, textColor=_PDF_MUTED))]

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    buf.seek(0)
    return buf


@app.route('/finance/download')
def finance_download():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    guard = _require_admin_level()
    if guard:
        return guard

    data = _load_finance_overview()
    pdf_buf = _build_finance_pdf(data['entries'], data['totals'], data['types'])
    fname = f"Finance_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    return send_file(pdf_buf, mimetype='application/pdf', as_attachment=True, download_name=fname)


def _validate_user_form(firstname, lastname, email, phone, gender):
    errors = {}

    if not firstname:
        errors['firstname'] = 'First name is required.'
    elif len(firstname) < 2:
        errors['firstname'] = 'First name must be at least 2 characters.'

    if not lastname:
        errors['lastname'] = 'Last name is required.'
    elif len(lastname) < 2:
        errors['lastname'] = 'Last name must be at least 2 characters.'

    if not email:
        errors['email'] = 'Email is required.'
    elif not _email_re.match(email):
        errors['email'] = 'Please enter a valid email address.'

    if not phone:
        errors['phone'] = 'Phone number is required.'
    elif not _phone_re.match(phone):
        errors['phone'] = 'Please enter a valid 10-digit phone number.'

    if gender not in ('Male', 'Female', 'Other'):
        errors['gender'] = 'Please select a valid gender.'

    return errors


@app.route('/users/add')
def add_user_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if _get_current_user_type() not in (_rid('Master Admin'), _rid('Users')):
        flash('Only Master Admin and Users can register new accounts.', 'danger')
        return redirect(url_for('dashboard'))
    me_type = _get_current_user_type()
    types = _load_user_types()
    if me_type != _rid('Master Admin'):
        allowed = {_rid('Users'), _rid('Driver'), _rid('Room Renter')}
        types = [t for t in types if t['id'] in allowed]
    return render_template('add_user.html', me_type=me_type, types=types)


@app.route('/users/types/create', methods=['POST'])
def create_user_type():
    if 'user_id' not in session:
        return jsonify(success=False, message='Session expired. Please login again.'), 401
    if _get_current_user_type() != _rid('Master Admin'):
        return jsonify(success=False, message='Only the Master Admin can create user types.'), 403

    name = request.form.get('typename', '').strip()
    if not name:
        return jsonify(success=False, message='Type name is required.'), 400
    if len(name) < 2 or len(name) > 30:
        return jsonify(success=False, message='Type name must be 2-30 characters.'), 400

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM usertype WHERE LOWER(typename) = LOWER(%s) LIMIT 1', (name,))
        if cursor.fetchone():
            cursor.close()
            return jsonify(success=False, message=f'User type "{name}" already exists.'), 400

        attempt = 0
        while True:
            try:
                cursor.execute('INSERT INTO usertype (typename) VALUES (%s) RETURNING id', (name,))
                new_id = cursor.fetchone()['id']
                conn.commit()
                break
            except psycopg2.IntegrityError as ie:
                conn.rollback()
                if getattr(ie, 'pgcode', None) == '23505' and 'typename' in ((getattr(ie.diag, 'constraint_name', '') or '') + (getattr(ie.diag, 'message_primary', '') or '')):
                    cursor.close()
                    return jsonify(success=False, message=f'User type "{name}" already exists.'), 400
                if attempt == 0 and _is_pk_violation(ie):
                    _sync_usertype_id_sequence()
                    attempt += 1
                    continue
                app.logger.error('create_user_type failed: %s | %s | %s',
                                 ie.pgcode,
                                 getattr(ie.diag, 'constraint_name', ''),
                                 getattr(ie.diag, 'message_primary', ''))
                return jsonify(success=False, message='Could not add this user type. Please try again.'), 500

        cursor.close()
        return jsonify(success=True, message=f'User type "{name}" added successfully.', id=new_id)
    except Exception:
        if conn:
            conn.rollback()
        return jsonify(success=False, message='Database error. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/users/create', methods=['POST'])
def create_user():
    is_ajax = request.form.get('ajax') == '1'

    if 'user_id' not in session:
        if is_ajax:
            return jsonify(success=False, message='Session expired. Please login again.'), 401
        return redirect(url_for('login'))

    # Registration (Add User): Master Admin and Users only — never Admin.
    me_t = _get_current_user_type()
    if me_t not in (_rid('Master Admin'), _rid('Users')):
        msg = 'You do not have permission to register users.'
        if is_ajax:
            return jsonify(success=False, message=msg), 403
        flash(msg, 'danger')
        return redirect(url_for('dashboard'))

    firstname = request.form.get('firstname', '').strip()
    lastname = request.form.get('lastname', '').strip()
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    gender = request.form.get('gender', '')
    istype = request.form.get('istype', '')
    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')

    def fail(errors, message):
        if is_ajax:
            return jsonify(success=False, message=message, errors=errors), 400
        if errors:
            for field, msg in errors.items():
                flash(f'{field.replace("_", " ").title()}: {msg}', 'danger')
        else:
            flash(message, 'danger')
        return redirect(url_for('add_user_page'))

    errors = _validate_user_form(firstname, lastname, email, phone, gender)

    if not _is_valid_type(istype):
        errors['istype'] = 'Please select a valid user type.'
    elif me_t == _rid('Users') and istype.isdigit() and int(istype) not in (
            {_rid('Users'), _rid('Driver'), _rid('Room Renter')} - {None}):
        errors['istype'] = 'You can only register Users, Drivers or Room Renters.'

    if not password:
        errors['password'] = 'Password is required.'
    elif len(password) < 6:
        errors['password'] = 'Password must be at least 6 characters.'
    elif not any(c.isupper() for c in password):
        errors['password'] = 'Password must contain at least one uppercase letter.'
    elif not any(c.isdigit() for c in password):
        errors['password'] = 'Password must contain at least one number.'

    if not confirm_password:
        errors['confirm_password'] = 'Please confirm the password.'
    elif password != confirm_password:
        errors['confirm_password'] = 'Passwords do not match.'

    if errors:
        return fail(errors, 'Please fix the highlighted fields.')

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE LOWER(TRIM(email)) = LOWER(%s) LIMIT 1', (email,))
        if cursor.fetchone():
            cursor.close()
            return fail({'email': 'This email is already registered.'}, 'Please fix the highlighted fields.')

        insert_sql = """
            INSERT INTO users (firstname, lastname, email, phone, gender, password, istype)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        params = (firstname, lastname, email, phone, gender, password, int(istype))

        attempt = 0
        while True:
            try:
                cursor.execute(insert_sql, params)
                conn.commit()
                break
            except psycopg2.IntegrityError as ie:
                conn.rollback()
                if _is_email_unique_violation(ie):
                    cursor.close()
                    return fail({'email': 'This email is already registered.'},
                                'Please fix the highlighted fields.')
                if attempt == 0:
                    _sync_users_id_sequence()
                    attempt += 1
                    continue
                cursor.close()
                return fail({}, 'Could not add this user due to a database constraint. Please try again.')

        cursor.close()

        if is_ajax:
            return jsonify(success=True, message='User added successfully.')
        flash('User added successfully.', 'success')
        return redirect(url_for('dashboard'))
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        if is_ajax:
            return jsonify(success=False, message='Database error. Please try again.'), 500
        flash('Database error. Please try again.', 'danger')
        return redirect(url_for('add_user_page'))
    finally:
        if conn:
            conn.close()


@app.route('/users/update', methods=['POST'])
def update_user():
    if 'user_id' not in session:
        return jsonify(success=False, message='Session expired. Please login again.'), 401
    if _get_current_user_type() not in (_rid('Master Admin'), _rid('Admin')):
        return jsonify(success=False, message='Only Master Admin or Admin can modify users.'), 403

    user_id = request.form.get('id', '')
    firstname = request.form.get('firstname', '').strip()
    lastname = request.form.get('lastname', '').strip()
    email = request.form.get('email', '').strip()
    phone = request.form.get('phone', '').strip()
    gender = request.form.get('gender', '')
    istype = request.form.get('istype', '')

    if not user_id or not user_id.isdigit():
        return jsonify(success=False, message='Invalid user selected.'), 400

    errors = _validate_user_form(firstname, lastname, email, phone, gender)
    if not _is_valid_type(istype):
        errors['istype'] = 'Please select a valid user type.'

    if errors:
        return jsonify(success=False, message='Please fix the highlighted fields.', errors=errors), 400

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE email = %s AND id <> %s LIMIT 1', (email, int(user_id)))
        if cursor.fetchone():
            cursor.close()
            return jsonify(success=False, message='Please fix the highlighted fields.',
                           errors={'email': 'This email is already used by another user.'}), 400

        cursor.execute(
            'UPDATE users SET firstname = %s, lastname = %s, email = %s, phone = %s, gender = %s, istype = %s WHERE id = %s',
            (firstname, lastname, email, phone, gender, int(istype), int(user_id))
        )
        conn.commit()
        cursor.close()
        return jsonify(success=True, message='User updated successfully.')
    except Exception:
        if conn:
            conn.rollback()
        return jsonify(success=False, message='Database error. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/users/toggle-status', methods=['POST'])
def toggle_user_status():
    if 'user_id' not in session:
        return jsonify(success=False, message='Session expired. Please login again.'), 401
    if _get_current_user_type() not in (_rid('Master Admin'), _rid('Admin')):
        return jsonify(success=False, message='Only Master Admin or Admin can change user status.'), 403

    user_id = request.form.get('id', '')
    if not user_id or not user_id.isdigit():
        return jsonify(success=False, message='Invalid user selected.'), 400

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET isactive = NOT isactive WHERE id = %s RETURNING isactive', (int(user_id),))
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            cursor.close()
            return jsonify(success=False, message='User not found.'), 404
        conn.commit()
        cursor.close()
        status = 'activated' if row['isactive'] else 'deactivated'
        return jsonify(success=True, message=f'User {status} successfully.', isactive=row['isactive'])
    except Exception:
        if conn:
            conn.rollback()
        return jsonify(success=False, message='Database error. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/rides-management')
def rides_management():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if _get_current_user_type() == _rid('Room Renter'):
        flash('Room Renters can manage their tenancy from the Rental Management page.', 'info')
        return redirect(url_for('rental_management'))

    filter_year = request.args.get('year', '')
    data = _load_rides_overview(filter_year)
    me_type = _get_current_user_type()

    return render_template('RidesMangmnt.html',
                           drivers=data['drivers'], ledger=data['ledger'],
                           stats=data['stats'], fin_rows=data['fin_rows'],
                           monthly=data['monthly'], years=data['years'],
                           choices=data['choices'], filter_year=filter_year,
                           today=date.today().isoformat(),
                           rf_entries=data['rf_entries'], rf_types=data['rf_types'],
                           rf_banks=data['rf_banks'], rf_users=data['rf_users'],
                           rf_totals=data['rf_totals'],
                           me_type=me_type, me_type_name=_get_current_user_type_name())


_RIDE_IMG_FIELDS = (('dlimage', 'Driving licence'), ('aadharimage', 'Aadhaar'),
                    ('driverimage', 'Driver photo'))


def _validate_driver_form(form):
    """Shared validation for driver create/update. Returns (errors, values)."""
    errors = {}
    userid = form.get('userid', '').strip()
    aadharno = form.get('aadharno', '').strip()
    license_no = form.get('license_no', '').strip().upper()
    vehicle_no = re.sub(r'\s+', '', form.get('vehicle_no', '').strip().upper())
    alt_phone = form.get('alt_phone', '').strip()
    address = form.get('address', '').strip()
    joining = form.get('joiningdate', '').strip()

    uid = None
    if not userid or not userid.isdigit():
        errors['userid'] = 'Please select a driver (user account).'
    else:
        uid = int(userid)

    if not _aadhar_re.match(aadharno):
        errors['aadharno'] = 'Aadhaar number must be exactly 12 digits.'

    if len(license_no) < 4 or len(license_no) > 30:
        errors['license_no'] = 'Enter a valid driving licence number (4-30 characters).'

    if vehicle_no and len(vehicle_no) > 25:
        errors['vehicle_no'] = 'Vehicle number must be within 25 characters.'

    if alt_phone and not _phone_re.match(alt_phone):
        errors['alt_phone'] = 'Alternate mobile must be exactly 10 digits.'

    join_date = None
    if joining:
        try:
            join_date = datetime.strptime(joining, '%Y-%m-%d').date()
        except ValueError:
            errors['joiningdate'] = 'Enter a valid date.'

    return errors, {'uid': uid, 'aadharno': aadharno, 'license_no': license_no,
                    'vehicle_no': vehicle_no or None, 'alt_phone': alt_phone or None,
                    'address': address or None, 'join_date': join_date}


def _load_rides_overview(filter_year=None):
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()

        me = session.get('user_id')
        is_driver = 'user_id' in session and _get_current_user_type() == _rid('Driver')
        own_sql = 'AND d.userid = %s' if is_driver else ''
        own_params = (me,) if is_driver else ()

        year_where = ''
        year_params = ()
        if filter_year and filter_year.isdigit():
            year_where = 'AND rd.ride_date >= %s AND rd.ride_date < %s'
            y = int(filter_year)
            year_params = (date(y, 1, 1), date(y + 1, 1, 1))

        cursor.execute(f"""
            SELECT d.id, d.userid, ut.typename AS type_name,
                   u.firstname, u.lastname, u.email, u.phone,
                   d.aadharno, d.license_no, d.vehicle_no, d.alt_phone, d.address,
                   d.dlimage, d.aadharimage, d.driverimage, d.joiningdate, d.created_at,
                   COALESCE(agg.total_amount, 0)::float AS total_paid,
                   COALESCE(agg.total_km, 0)::float AS total_km,
                   COALESCE(agg.rides, 0) AS rides_count,
                   lm.last_meter_end
            FROM drivers d
            JOIN users u ON u.id = d.userid
            LEFT JOIN usertype ut ON ut.id = d.usertypeid
            LEFT JOIN (
                SELECT driverid, SUM(amount) AS total_amount, SUM(km_driven) AS total_km,
                       COUNT(*) AS rides
                FROM ridedetails GROUP BY driverid
            ) agg ON agg.driverid = d.id
            LEFT JOIN LATERAL (
                SELECT rd.meter_end::float AS last_meter_end
                FROM ridedetails rd
                WHERE rd.driverid = d.id AND rd.meter_end IS NOT NULL
                ORDER BY rd.ride_date DESC, rd.id DESC
                LIMIT 1
            ) lm ON TRUE
            WHERE TRUE {own_sql}
            ORDER BY d.created_at DESC
        """, own_params)
        drivers = cursor.fetchall()

        cursor.execute(f"""
            SELECT rd.id, rd.driverid, rd.ride_date, rd.km_driven::float AS km_driven,
                   rd.meter_start::float AS meter_start, rd.meter_end::float AS meter_end,
                   rd.meter_image, rd.amount::float AS amount, rd.remarks, rd.currentdate,
                   u.firstname, u.lastname, d.vehicle_no
            FROM ridedetails rd
            JOIN drivers d ON d.id = rd.driverid
            JOIN users u ON u.id = d.userid
            WHERE TRUE {own_sql} {year_where}
            ORDER BY rd.ride_date DESC, rd.id DESC
        """, own_params + year_params)
        ledger = cursor.fetchall()

        last_meter_end = None
        if is_driver:
            cursor.execute("""
                SELECT rd.meter_end::float AS meter_end
                FROM ridedetails rd
                JOIN drivers d ON d.id = rd.driverid
                WHERE d.userid = %s AND rd.meter_end IS NOT NULL
                ORDER BY rd.ride_date DESC, rd.id DESC
                LIMIT 1
            """, (me,))
            lm_row = cursor.fetchone()
            if lm_row:
                last_meter_end = lm_row['meter_end']

        now_y, now_m = date.today().year, date.today().month
        cursor.execute(f"""
            SELECT
              (SELECT COUNT(*) FROM drivers d WHERE TRUE {own_sql}) AS drivers,
              (SELECT COALESCE(SUM(rd.km_driven), 0)::float FROM ridedetails rd
                 JOIN drivers d ON d.id = rd.driverid
                 WHERE EXTRACT(YEAR FROM rd.ride_date) = %s {own_sql}) AS km_year,
              (SELECT COALESCE(SUM(rd.km_driven), 0)::float FROM ridedetails rd
                 JOIN drivers d ON d.id = rd.driverid
                 WHERE EXTRACT(YEAR FROM rd.ride_date) = %s
                   AND EXTRACT(MONTH FROM rd.ride_date) = %s {own_sql}) AS km_month,
              (SELECT COALESCE(SUM(rd.amount), 0)::float FROM ridedetails rd
                 JOIN drivers d ON d.id = rd.driverid
                 WHERE EXTRACT(YEAR FROM rd.ride_date) = %s
                   AND EXTRACT(MONTH FROM rd.ride_date) = %s {own_sql}) AS paid_month,
               (SELECT COALESCE(SUM(rd.amount), 0)::float FROM ridedetails rd
                  JOIN drivers d ON d.id = rd.driverid
                  WHERE TRUE {own_sql}) AS paid_all
        """, own_params + (now_y,) + own_params + (now_y, now_m) + own_params + (now_y, now_m) + own_params + own_params)
        stats = cursor.fetchone()

        cursor.execute(f"""
            SELECT DISTINCT EXTRACT(YEAR FROM rd.ride_date)::int AS year
            FROM ridedetails rd
            JOIN drivers d ON d.id = rd.driverid
            WHERE TRUE {own_sql}
            ORDER BY year DESC
        """, own_params)
        years = [row['year'] for row in cursor.fetchall()]
        if now_y not in years:
            years.insert(0, now_y)

        if is_driver:
            choices = []
        else:
            cursor.execute("""
                SELECT u.id, u.firstname, u.lastname, u.email, ut.typename AS type_name
                FROM users u
                JOIN usertype ut ON ut.id = u.istype
                WHERE u.isactive = TRUE
                  AND ut.id = 3
                  AND NOT EXISTS (SELECT 1 FROM drivers d WHERE d.userid = u.id)
                ORDER BY u.firstname
            """)
            choices = cursor.fetchall()

        # ----- rides finance (separate) -----
        cursor.execute(f"""
            SELECT u.firstname || ' ' || u.lastname AS driver,
                   COUNT(rd.id) AS rides,
                   COALESCE(SUM(rd.km_driven), 0)::float AS km,
                   COALESCE(SUM(rd.amount), 0)::float AS amount
            FROM ridedetails rd
            JOIN drivers d ON d.id = rd.driverid
            JOIN users u ON u.id = d.userid
            WHERE TRUE {own_sql}
            GROUP BY driver ORDER BY amount DESC
        """, own_params)
        fin_rows = cursor.fetchall()

        cursor.execute(f"""
            SELECT TO_CHAR(rd.ride_date, 'YYYY-MM') AS ym,
                   COUNT(*) AS rides,
                   COALESCE(SUM(rd.km_driven), 0)::float AS km,
                   COALESCE(SUM(rd.amount), 0)::float AS amount
            FROM ridedetails rd
            JOIN drivers d ON d.id = rd.driverid
            WHERE TRUE {own_sql}
            GROUP BY ym ORDER BY ym DESC
        """, own_params)
        monthly = cursor.fetchall()

        # ----- rides finance: described (managed) amounts vs total -----
        cursor.execute('SELECT id, type_name FROM finance_type_master WHERE isactive = TRUE ORDER BY id')
        rf_types = cursor.fetchall()
        cursor.execute('SELECT bank_name FROM bank_master WHERE isactive = TRUE ORDER BY bank_name')
        rf_banks = [r['bank_name'] for r in cursor.fetchall()]

        cursor.execute("""
            SELECT fe.id, fe.type_id, tm.type_name,
                   fe.amount::float AS amount, fe.bank_name, fe.fd_no,
                   fe.user_id, u.firstname, u.lastname, u.email,
                   fe.remarks, fe.entry_date
            FROM ride_finance_entries fe
            JOIN finance_type_master tm ON tm.id = fe.type_id
            LEFT JOIN users u ON u.id = fe.user_id
            ORDER BY fe.entry_date DESC, fe.id DESC
        """)
        rf_entries = cursor.fetchall()

        cursor.execute("""
            SELECT u.id, u.firstname, u.lastname, u.email
            FROM users u
            JOIN usertype ut ON ut.id = u.istype
            WHERE u.isactive = TRUE AND ut.id IN (1, 2)
            ORDER BY u.firstname
        """)
        rf_users = cursor.fetchall()

        cursor.execute("""
            SELECT
              (SELECT COALESCE(SUM(amount), 0)::float FROM ridedetails) AS total_rides,
              (SELECT COALESCE(SUM(amount), 0)::float FROM ride_finance_entries) AS managed
        """)
        rf_totals = cursor.fetchone()
        rf_totals['unmanaged'] = round(max((rf_totals['total_rides'] or 0) - (rf_totals['managed'] or 0), 0.0), 2)

        cursor.close()
        return {'drivers': drivers, 'ledger': ledger, 'stats': stats,
                'fin_rows': fin_rows, 'monthly': monthly,
                'rf_entries': rf_entries, 'rf_types': rf_types, 'rf_banks': rf_banks,
                'rf_users': rf_users, 'rf_totals': rf_totals,
                'years': years, 'choices': choices}
    except Exception:
        app.logger.exception('rides overview failed')
        return {'drivers': [], 'ledger': [], 'stats': None, 'fin_rows': [],
                'monthly': [], 'rf_entries': [], 'rf_types': [], 'rf_banks': [],
                'rf_users': [],
                'rf_totals': {'total_rides': 0, 'managed': 0, 'unmanaged': 0},
                'years': [], 'choices': []}
    finally:
        if conn:
            conn.close()


def _driver_upload_errors():
    """Handle the three optional driver images. Returns ({field: path}, {field: err})."""
    paths, errs = {}, {}
    for field, label in _RIDE_IMG_FIELDS:
        rel, err = _save_upload(request.files.get(field), _ALLOWED_IMG_EXT)
        if err:
            errs[field] = f'{label} image must be PNG/JPG/WEBP (max 5 MB).'
        else:
            paths[field] = rel
    return paths, errs


@app.route('/driver/create', methods=['POST'])
def create_driver():
    denied = _require_admin_level()
    if denied:
        return denied

    img_paths, img_errs = _driver_upload_errors()
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        errors, v = _validate_driver_form(request.form)
        errors.update(img_errs)

        if 'userid' not in errors and v['uid'] is not None:
            cursor.execute('SELECT id, isactive, phone FROM users WHERE id = %s LIMIT 1', (v['uid'],))
            target = cursor.fetchone()
            if not target:
                errors['userid'] = 'Selected user does not exist.'
            elif not target['isactive']:
                errors['userid'] = 'Selected user is inactive.'
            elif v['alt_phone'] and target['phone'] == v['alt_phone']:
                errors['alt_phone'] = 'Alternate mobile must differ from the registered mobile number.'
            else:
                cursor.execute('SELECT 1 FROM drivers WHERE userid = %s LIMIT 1', (v['uid'],))
                if cursor.fetchone():
                    errors['userid'] = 'This user already has a driver record.'

        if 'aadharno' not in errors and v['aadharno']:
            cursor.execute('SELECT 1 FROM drivers WHERE aadharno = %s LIMIT 1', (v['aadharno'],))
            if cursor.fetchone():
                errors['aadharno'] = 'This Aadhaar number is already registered as a driver.'

        if errors:
            cursor.close()
            return jsonify(success=False, message='Please fix the highlighted fields.', errors=errors), 400

        cursor.execute('SELECT istype FROM users WHERE id = %s', (v['uid'],))
        usertypeid = cursor.fetchone()['istype']

        cursor.execute("""
            INSERT INTO drivers
                (userid, usertypeid, aadharno, license_no, vehicle_no, alt_phone,
                 address, dlimage, aadharimage, driverimage, joiningdate)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (v['uid'], usertypeid, v['aadharno'], v['license_no'], v['vehicle_no'],
              v['alt_phone'], v['address'], img_paths.get('dlimage'),
              img_paths.get('aadharimage'), img_paths.get('driverimage'), v['join_date']))
        conn.commit()
        cursor.close()
        return jsonify(success=True, message='Driver added successfully.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        app.logger.exception('create_driver failed')
        return jsonify(success=False, message='Could not save the driver. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/driver/update', methods=['POST'])
def update_driver():
    denied = _require_admin_level()
    if denied:
        return denied

    driver_id = request.form.get('driver_id', '').strip()
    if not driver_id.isdigit():
        return jsonify(success=False, message='Invalid driver.'), 400

    img_paths, img_errs = _driver_upload_errors()
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""SELECT d.id, d.userid, u.phone FROM drivers d
                          JOIN users u ON u.id = d.userid WHERE d.id = %s LIMIT 1""", (int(driver_id),))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return jsonify(success=False, message='Driver not found.'), 404

        form = dict(request.form)
        form['userid'] = str(row['userid'])  # driver's linked user never changes here
        errors, v = _validate_driver_form(form)
        errors.update(img_errs)

        if 'aadharno' not in errors and v['aadharno']:
            cursor.execute('SELECT 1 FROM drivers WHERE aadharno = %s AND id <> %s LIMIT 1',
                           (v['aadharno'], int(driver_id)))
            if cursor.fetchone():
                errors['aadharno'] = 'This Aadhaar number belongs to another driver.'

        if 'alt_phone' not in errors and v['alt_phone'] and row['phone'] == v['alt_phone']:
            errors['alt_phone'] = 'Alternate mobile must differ from the registered mobile number.'

        if errors:
            cursor.close()
            return jsonify(success=False, message='Please fix the highlighted fields.', errors=errors), 400

        sets = ['aadharno = %s', 'license_no = %s', 'vehicle_no = %s',
                'alt_phone = NULLIF(%s, \'\')', 'address = NULLIF(%s, \'\')',
                'joiningdate = COALESCE(%s, joiningdate)']
        args = [v['aadharno'], v['license_no'], v['vehicle_no'],
                v['alt_phone'] or '', v['address'] or '', v['join_date']]
        for field in ('dlimage', 'aadharimage', 'driverimage'):
            if img_paths.get(field):
                sets.append(f'{field} = %s')
                args.append(img_paths[field])
        args.append(int(driver_id))
        cursor.execute(f"UPDATE drivers SET {', '.join(sets)} WHERE id = %s", tuple(args))
        conn.commit()
        cursor.close()
        return jsonify(success=True, message='Driver details updated successfully.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        app.logger.exception('update_driver failed')
        return jsonify(success=False, message='Could not update the driver. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/driver/delete', methods=['POST'])
def delete_driver():
    denied = _require_admin_level()
    if denied:
        return denied

    driver_id = request.form.get('driver_id', '').strip()
    if not driver_id.isdigit():
        return jsonify(success=False, message='Invalid driver.'), 400

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM drivers WHERE id = %s FOR UPDATE', (int(driver_id),))
        if not cursor.fetchone():
            cursor.close()
            conn.rollback()
            return jsonify(success=False, message='Driver not found.'), 404

        cursor.execute("""
            DELETE FROM ridedetails WHERE driverid = %s RETURNING meter_image
        """, (int(driver_id),))
        for r in cursor.fetchall():
            _remove_upload(r['meter_image'])
        cursor.execute("""
            SELECT dlimage, aadharimage, driverimage FROM drivers WHERE id = %s
        """, (int(driver_id),))
        imgs = cursor.fetchone()
        cursor.execute('DELETE FROM drivers WHERE id = %s', (int(driver_id),))
        conn.commit()
        cursor.close()
        if imgs:
            for col in ('dlimage', 'aadharimage', 'driverimage'):
                _remove_upload(imgs[col])
        return jsonify(success=True, message='Driver and all ride records deleted.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        app.logger.exception('delete_driver failed')
        return jsonify(success=False, message='Could not delete the driver. Please try again.'), 500
    finally:
        if conn:
            conn.close()


def _validate_ride_form(form):
    errors = {}
    driverid = form.get('driverid', '').strip()
    date_str = form.get('ride_date', '').strip()
    km_raw = form.get('km_driven', '').strip()
    ms_raw = form.get('meter_start', '').strip()
    me_raw = form.get('meter_end', '').strip()
    amount_raw = form.get('amount', '').strip().replace(',', '')
    remarks = form.get('remarks', '').strip()

    did = None
    if not driverid or not driverid.isdigit():
        errors['driverid'] = 'Please select a driver.'
    else:
        did = int(driverid)

    ride_date = date.today()
    if date_str:
        try:
            ride_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            errors['ride_date'] = 'Enter a valid date.'

    km = None
    try:
        km = round(float(km_raw), 1)
        if km < 0 or km > 9999999:
            raise ValueError
    except (TypeError, ValueError):
        errors['km_driven'] = 'Enter valid kilometres driven (0 or more).'

    def _num(raw):
        raw = raw.replace(',', '')
        if not raw:
            return None
        try:
            val = round(float(raw), 1)
            if val < 0:
                raise ValueError
            return val
        except (TypeError, ValueError):
            return False  # sentinel: present but invalid

    ms, me = _num(ms_raw), _num(me_raw)
    if ms is False:
        errors['meter_start'] = 'Enter a valid meter reading.'
    if me is False:
        errors['meter_end'] = 'Enter a valid meter reading.'
    if ms not in (None, False) and me not in (None, False) and me < ms:
        errors['meter_end'] = 'End reading cannot be less than start reading.'
    if km is not None and ms not in (None, False) and me not in (None, False):
        if abs((me - ms) - km) > 0.05:
            errors['km_driven'] = (f'KM driven should equal end âˆ’ start '
                                   f'(= {round(me - ms, 1)} km as per readings).')

    amount = None
    try:
        amount = round(float(amount_raw), 2)
        if amount < 0 or amount > 10000000:
            raise ValueError
    except (TypeError, ValueError):
        errors['amount'] = 'Enter a valid amount (0 or more).'

    if len(remarks) > 500:
        errors['remarks'] = 'Remarks must be within 500 characters.'

    return errors, {'did': did, 'ride_date': ride_date, 'km': km,
                    'ms': None if ms in (None, False) else ms,
                    'me': None if me in (None, False) else me,
                    'amount': amount, 'remarks': remarks}


@app.route('/ride/add', methods=['POST'])
def add_ride():
    if 'user_id' not in session:
        return jsonify(success=False, message='Session expired. Please login again.'), 401

    me_t = _get_current_user_type()
    staff_types = {_rid('Master Admin'), _rid('Admin')}
    if me_t not in (staff_types | {_rid('Driver')}):
        return jsonify(success=False,
                       message='You do not have permission to perform this action.'), 403

    if me_t == _rid('Driver'):
        _raw_did = request.form.get('driverid', '').strip()
        conn_o = None
        owns = False
        try:
            conn_o = get_db()
            cur_o = conn_o.cursor()
            owns = _driver_belongs_to_user(cur_o, int(_raw_did) if _raw_did.isdigit() else None)
            cur_o.close()
        except Exception:
            pass
        finally:
            if conn_o:
                conn_o.close()
        if not owns:
            return jsonify(success=False,
                           message='You can only add rides for your own driver profile.'), 403

    errors, v = _validate_ride_form(request.form)
    meter_rel, meter_err = _save_upload(request.files.get('meter_image'), _ALLOWED_IMG_EXT)
    if meter_err:
        errors['meter_image'] = 'Meter reading image is required â€” PNG/JPG/WEBP (max 5 MB).'
    elif not meter_rel:
        errors['meter_image'] = 'Meter reading image is required.'

    if errors:
        return jsonify(success=False, message='Please fix the highlighted fields.', errors=errors), 400

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM drivers WHERE id = %s LIMIT 1', (v['did'],))
        if not cursor.fetchone():
            cursor.close()
            return jsonify(success=False, message='Driver not found.',
                           errors={'driverid': 'Driver record not found.'}), 400

        cursor.execute("""
            INSERT INTO ridedetails
                (driverid, ride_date, km_driven, meter_start, meter_end, meter_image, amount, remarks)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NULLIF(%s, ''))
        """, (v['did'], v['ride_date'], v['km'], v['ms'], v['me'], meter_rel,
              v['amount'], v['remarks']))
        conn.commit()
        cursor.close()
        return jsonify(success=True,
                       message=f'Ride recorded: {v["km"]:,.1f} km, â‚¹{v["amount"]:,.2f}.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        _remove_upload(meter_rel)
        app.logger.exception('add_ride failed')
        return jsonify(success=False, message='Could not record the ride. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/ride/update', methods=['POST'])
def update_ride():
    denied = _require_admin_level()
    if denied:
        return denied

    ride_id = request.form.get('ride_id', '').strip()
    if not ride_id.isdigit():
        return jsonify(success=False, message='Invalid ride record.'), 400

    errors, v = _validate_ride_form(request.form)
    new_meter, meter_err = _save_upload(request.files.get('meter_image'), _ALLOWED_IMG_EXT)
    if meter_err:
        errors['meter_image'] = 'Meter image must be PNG/JPG/WEBP (max 5 MB).'
    old_meter = None
    if errors:
        return jsonify(success=False, message='Please fix the highlighted fields.', errors=errors), 400

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT driverid, meter_image FROM ridedetails WHERE id = %s FOR UPDATE',
                       (int(ride_id),))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            conn.rollback()
            return jsonify(success=False, message='Ride record not found.'), 404
        old_meter = row['meter_image']
        keep_driver = v['did'] or row['driverid']

        if new_meter:
            cursor.execute("""
                UPDATE ridedetails SET driverid = %s, ride_date = %s, km_driven = %s,
                       meter_start = %s, meter_end = %s, meter_image = %s,
                       amount = %s, remarks = NULLIF(%s, '')
                WHERE id = %s
            """, (keep_driver, v['ride_date'], v['km'], v['ms'], v['me'], new_meter,
                  v['amount'], v['remarks'], int(ride_id)))
        else:
            cursor.execute("""
                UPDATE ridedetails SET driverid = %s, ride_date = %s, km_driven = %s,
                       meter_start = %s, meter_end = %s,
                       amount = %s, remarks = NULLIF(%s, '')
                WHERE id = %s
            """, (keep_driver, v['ride_date'], v['km'], v['ms'], v['me'],
                  v['amount'], v['remarks'], int(ride_id)))
        conn.commit()
        cursor.close()
        if new_meter and old_meter:
            _remove_upload(old_meter)
        return jsonify(success=True, message=f'Ride updated: {v["km"]:,.1f} km, â‚¹{v["amount"]:,.2f}.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        _remove_upload(new_meter)
        app.logger.exception('update_ride failed')
        return jsonify(success=False, message='Could not update the ride. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/ride/delete', methods=['POST'])
def delete_ride():
    denied = _require_admin_level()
    if denied:
        return denied

    ride_id = request.form.get('ride_id', '').strip()
    if not ride_id.isdigit():
        return jsonify(success=False, message='Invalid ride record.'), 400

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM ridedetails WHERE id = %s RETURNING meter_image', (int(ride_id),))
        removed = cursor.fetchone()
        conn.commit()
        cursor.close()
        if not removed:
            return jsonify(success=False, message='Ride record not found.'), 404
        _remove_upload(removed['meter_image'])
        return jsonify(success=True, message='Ride record deleted.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        app.logger.exception('delete_ride failed')
        return jsonify(success=False, message='Could not delete the ride. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/driver/rides/<int:driver_id>')
def driver_rides_history(driver_id):
    if 'user_id' not in session:
        return jsonify(success=False, message='Session expired. Please login again.'), 401

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT d.id, u.firstname, u.lastname, u.phone, d.alt_phone,
                   d.license_no, d.vehicle_no, d.aadharno, d.joiningdate
            FROM drivers d JOIN users u ON u.id = d.userid
            WHERE d.id = %s LIMIT 1
        """, (driver_id,))
        driver = cursor.fetchone()
        if not driver:
            cursor.close()
            return jsonify(success=False, message='Driver not found.'), 404

        cursor.execute("""
            SELECT id, ride_date, km_driven::float AS km_driven,
                   meter_start::float AS meter_start, meter_end::float AS meter_end,
                   meter_image, amount::float AS amount, remarks, currentdate
            FROM ridedetails WHERE driverid = %s
            ORDER BY ride_date DESC, id DESC
        """, (driver_id,))
        rides = cursor.fetchall()

        # DB stores naive local wall time; detect its offset from UTC once so we can
        # render every timestamp in Asia/Kolkata regardless of the server timezone.
        cursor.execute("SELECT EXTRACT(EPOCH FROM ((now() AT TIME ZONE 'UTC') - now()::timestamp))::int AS d")
        delta = int(cursor.fetchone()['d'] or 0)
        ist_tz = timezone(timedelta(hours=5, minutes=30))
        for r in rides:
            r['ride_date'] = r['ride_date'].isoformat() if r['ride_date'] else ''
            r['recorded_on'] = ''
            cd = r.pop('currentdate', None)
            if cd is not None:
                utc_dt = cd.replace(tzinfo=timezone.utc) + timedelta(seconds=delta)
                r['recorded_on'] = utc_dt.astimezone(ist_tz).strftime('%d %b %Y, %I:%M %p') + ' IST'

        cursor.close()
        return jsonify(success=True, driver=driver, rides=rides)
    except Exception:
        app.logger.exception('driver_rides_history failed')
        return jsonify(success=False, message='Could not load ride history.'), 500
    finally:
        if conn:
            conn.close()


def _rides_unmanaged_left(cursor, exclude_id=None):
    """Total ride payouts minus described amounts; can never go below zero."""
    cursor.execute('SELECT COALESCE(SUM(amount), 0)::float AS total FROM ridedetails')
    total = cursor.fetchone()['total'] or 0
    if exclude_id:
        cursor.execute('SELECT COALESCE(SUM(amount), 0)::float AS managed '
                       'FROM ride_finance_entries WHERE id <> %s', (exclude_id,))
    else:
        cursor.execute('SELECT COALESCE(SUM(amount), 0)::float AS managed FROM ride_finance_entries')
    return round(total - (cursor.fetchone()['managed'] or 0), 2)


def _rides_finance_master_sets(cursor):
    cursor.execute('SELECT id, type_name FROM finance_type_master WHERE isactive = TRUE')
    types_by_id = {r['id']: r['type_name'] for r in cursor.fetchall()}
    cursor.execute('SELECT bank_name FROM bank_master WHERE isactive = TRUE')
    banks_set = {r['bank_name'] for r in cursor.fetchall()}
    return types_by_id, banks_set


@app.route('/rides-finance/entry/create', methods=['POST'])
def ride_finance_create():
    guard = _require_admin_level()
    if guard:
        return guard

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        types_by_id, banks_set = _rides_finance_master_sets(cursor)
        errors, v = _validate_finance_form(request.form, types_by_id, banks_set)

        if not errors and v['uid'] is not None and not _finance_user_exists(cursor, v['uid']):
            errors['fin_user'] = 'Selected user account no longer exists.'
        if not errors and v['amount'] is not None:
            available = _rides_unmanaged_left(cursor)
            if v['amount'] > available + 1e-9:
                errors['amount'] = (f'Amount exceeds the unmanaged balance (\u20b9{available:,.2f} left). '
                                    f'Managed amount can never be more than the Total Rides Amount.')
        if errors:
            cursor.close()
            return jsonify(success=False, message='Please fix the highlighted fields.', errors=errors), 400

        cursor.execute("""
            INSERT INTO ride_finance_entries (type_id, amount, bank_name, fd_no, user_id, remarks, entry_date)
            VALUES (%s, %s, %s, NULLIF(%s, ''), %s, NULLIF(%s, ''), COALESCE(%s, CURRENT_DATE))
        """, (v['type_id'], v['amount'], v['bank'], v['fd_no'], v['uid'], v['remarks'], v['date']))
        conn.commit()
        cursor.close()
        return jsonify(success=True,
                       message=f'{v["type_name"]} of \u20b9{v["amount"]:,.2f} recorded successfully.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        app.logger.exception('ride_finance_create failed')
        return jsonify(success=False, message='Could not save the entry. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/rides-finance/entry/update', methods=['POST'])
def ride_finance_update():
    guard = _require_admin_level()
    if guard:
        return guard

    entry_id = request.form.get('id', '').strip()
    if not entry_id.isdigit():
        return jsonify(success=False, message='Invalid entry.'), 400

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM ride_finance_entries WHERE id = %s LIMIT 1', (int(entry_id),))
        if not cursor.fetchone():
            cursor.close()
            return jsonify(success=False, message='Entry not found.'), 404

        types_by_id, banks_set = _rides_finance_master_sets(cursor)
        errors, v = _validate_finance_form(request.form, types_by_id, banks_set)

        if not errors and v['uid'] is not None and not _finance_user_exists(cursor, v['uid']):
            errors['fin_user'] = 'Selected user account no longer exists.'
        if not errors and v['amount'] is not None:
            available = _rides_unmanaged_left(cursor, exclude_id=int(entry_id))
            if v['amount'] > available + 1e-9:
                errors['amount'] = (f'Amount exceeds the unmanaged balance (\u20b9{available:,.2f} left). '
                                    f'Managed amount can never be more than the Total Rides Amount.')
        if errors:
            cursor.close()
            return jsonify(success=False, message='Please fix the highlighted fields.', errors=errors), 400

        cursor.execute("""
            UPDATE ride_finance_entries
            SET type_id = %s, amount = %s, bank_name = %s, fd_no = NULLIF(%s, ''), user_id = %s,
                remarks = NULLIF(%s, ''), entry_date = COALESCE(%s, entry_date),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (v['type_id'], v['amount'], v['bank'], v['fd_no'], v['uid'],
              v['remarks'], v['date'], int(entry_id)))
        conn.commit()
        cursor.close()
        return jsonify(success=True,
                       message=f'Entry updated to {v["type_name"]}, \u20b9{v["amount"]:,.2f}.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        app.logger.exception('ride_finance_update failed')
        return jsonify(success=False, message='Could not update the entry. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/rides-finance/entry/delete', methods=['POST'])
def ride_finance_delete():
    guard = _require_admin_level()
    if guard:
        return guard

    entry_id = request.form.get('id', '').strip()
    if not entry_id.isdigit():
        return jsonify(success=False, message='Invalid entry.'), 400

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM ride_finance_entries WHERE id = %s', (int(entry_id),))
        deleted = cursor.rowcount
        conn.commit()
        cursor.close()
        if not deleted:
            return jsonify(success=False, message='Entry not found.'), 404
        return jsonify(success=True, message='Described amount entry deleted.')
    except Exception:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        app.logger.exception('ride_finance_delete failed')
        return jsonify(success=False, message='Could not delete the entry. Please try again.'), 500
    finally:
        if conn:
            conn.close()


@app.route('/rides/download/<int:driver_id>')
def driver_download_pdf(driver_id):
    """Per-driver statement ZIP: PDF report + licence/aadhaar/driver images."""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    me_t = _get_current_user_type()
    if me_t not in ({_rid('Master Admin'), _rid('Admin')} | {_rid('Driver')}):
        flash('You do not have permission to download this file.', 'danger')
        return redirect(url_for('dashboard'))
    if me_t == _rid('Driver'):
        conn_o = None
        owns = False
        try:
            conn_o = get_db()
            cur_o = conn_o.cursor()
            owns = _driver_belongs_to_user(cur_o, driver_id)
            cur_o.close()
        except Exception:
            pass
        finally:
            if conn_o:
                conn_o.close()
        if not owns:
            flash('You can only download your own ride statement.', 'danger')
            return redirect(url_for('rides_management'))

    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT d.*, u.firstname, u.lastname, u.email, u.phone, ut.typename AS type_name
            FROM drivers d JOIN users u ON u.id = d.userid
            LEFT JOIN usertype ut ON ut.id = d.usertypeid
            WHERE d.id = %s LIMIT 1
        """, (driver_id,))
        d = cursor.fetchone()
        if not d:
            cursor.close()
            flash('Driver record not found.', 'danger')
            return redirect(url_for('rides_management'))

        cursor.execute("""
            SELECT id, ride_date, km_driven::float AS km_driven, meter_start::float AS meter_start,
                   meter_end::float AS meter_end, meter_image, amount::float AS amount, remarks
            FROM ridedetails WHERE driverid = %s
            ORDER BY ride_date ASC, id ASC
        """, (driver_id,))
        rides = cursor.fetchall()
        cursor.close()

        safe_name = re.sub(r'[^A-Za-z0-9]+', '_', f"{d['firstname']}_{d['lastname']}").strip('_') or 'Driver'
        pdf_buf = _build_driver_pdf(d, rides)

        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f'{safe_name}_Ride_Report.pdf', pdf_buf.read())
            for col, label in (('dlimage', 'Driving_Licence'), ('aadharimage', 'Aadhaar'),
                               ('driverimage', 'Driver_Photo')):
                rel = d[col]
                if not rel:
                    continue
                fp = os.path.join(app.static_folder, rel)
                if os.path.exists(fp):
                    ext = rel.rsplit('.', 1)[-1].lower()
                    zf.write(fp, f'{label}_{safe_name}.{ext}')

        zbuf.seek(0)
        return send_file(zbuf, mimetype='application/zip', as_attachment=True,
                         download_name=f'{safe_name}_Ride_Documents.zip')
    except Exception:
        app.logger.exception('driver_download_pdf failed')
        flash('Could not generate the download package.', 'danger')
        return redirect(url_for('rides_management'))
    finally:
        if conn:
            conn.close()


def _build_driver_pdf(d, rides):
    """Statement PDF for one driver incl. meter-reading thumbnails."""
    total_km = sum(float(r['km_driven'] or 0) for r in rides)
    total_amt = sum(float(r['amount'] or 0) for r in rides)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=18 * mm,
                            title='Driver Ride Statement', author='PDM Rides Management')

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setStrokeColor(_PDF_LINE)
        canvas.setLineWidth(0.7)
        canvas.line(16 * mm, 13 * mm, A4[0] - 16 * mm, 13 * mm)
        canvas.setFont(_PDF_FONT, 7.5)
        canvas.setFillColor(_PDF_MUTED)
        canvas.drawString(16 * mm, 9 * mm, 'PDM â€¢ Rides Management â€” system generated document')
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f'Page {doc_.page}')
        canvas.restoreState()

    story = []
    ref = f'RID-{datetime.now().strftime("%Y%m%d%H%M")}'
    right_style = ParagraphStyle('r', fontName=_PDF_FONT, fontSize=8.5, leading=12, alignment=TA_RIGHT)
    band = Table([[
        [Paragraph('<font color="#67e8f9">PDM RIDES MANAGEMENT</font>',
                   ParagraphStyle('k', fontName=_PDF_FONT_B, fontSize=8, leading=10)),
         Spacer(1, 4),
         Paragraph('<font color="white">Driver Ride Statement</font>',
                   ParagraphStyle('t', fontName=_PDF_FONT_B, fontSize=17, leading=21))],
        [Paragraph(f'<font color="#bae6fd">Report Ref</font><br/><font color="white"><b>#{ref}</b></font>', right_style),
         Spacer(1, 3),
         Paragraph(f'<font color="#bae6fd">Generated</font><br/><font color="white">{datetime.now().strftime("%d %b %Y, %I:%M %p")}</font>', right_style)],
    ]], colWidths=[110 * mm, 68 * mm])
    band.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#0c4a6e')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (0, 0), 12),
        ('RIGHTPADDING', (-1, -1), (-1, -1), 12),
        ('LINEBELOW', (0, 0), (-1, -1), 2.5, colors.HexColor('#06b6d4')),
    ]))
    story += [band, Spacer(1, 8)]

    info = [
        ['Driver Name:', f"{d['firstname']} {d['lastname']}"],
        ['Phone / Alt Mobile:', f"{d['phone']}" + (f" / {d['alt_phone']}" if d['alt_phone'] else '')],
        ['Licence No:', d['license_no']],
        ['Vehicle No:', d['vehicle_no'] or '-'],
        ['Aadhaar:', d['aadharno']],
        ['Joining Date:', d['joiningdate'].strftime('%d %b %Y') if d['joiningdate'] else '-'],
    ]
    info_tbl = Table([[Paragraph(f'<b>{k}</b>', ParagraphStyle('il', fontName=_PDF_FONT, fontSize=9, leading=13)),
                       Paragraph(str(val_), ParagraphStyle('iv', fontName=_PDF_FONT, fontSize=9, leading=13))]
                      for k, val_ in info], colWidths=[45 * mm, 100 * mm])
    info_tbl.setStyle(TableStyle([
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2), ('TOPPADDING', (0, 0), (-1, -1), 2),
    ]))
    story += [_pdf_section('DRIVER DETAILS'), Spacer(1, 4), info_tbl, Spacer(1, 10)]

    story.append(_pdf_section(f'DAILY RIDE TRANSACTIONS ({len(rides)})'))
    story.append(Spacer(1, 4))
    if rides:
        head = ['#', 'Date', 'Meter Start', 'Meter End', 'KM Driven', 'Amount', 'Meter Image', 'Remarks']
        rows = []
        for i, r in enumerate(rides, 1):
            rem = (r['remarks'] or '-')
            if len(rem) > 28:
                rem = rem[:25] + '...'
            img_cell = '-'
            rel = r['meter_image']
            fp = os.path.join(app.static_folder, rel) if rel else None
            if fp and os.path.exists(fp):
                try:
                    img_cell = RLImage(fp, width=18 * mm, height=13 * mm)
                    img_cell.hAlign = 'CENTER'
                except Exception:
                    img_cell = 'View file'
            rows.append([
                str(i), r['ride_date'].strftime('%d %b %y') if r['ride_date'] else '-',
                f"{r['meter_start']:,.0f}" if r['meter_start'] is not None else '-',
                f"{r['meter_end']:,.0f}" if r['meter_end'] is not None else '-',
                f"{r['km_driven']:,.1f}", _money_str(r['amount']), img_cell, rem,
            ])
        rows.append(['', '', '', '', Paragraph(f'<b><font color="#059669">{total_km:,.1f} km</font></b>',
                                               ParagraphStyle('tf', fontName=_PDF_FONT, fontSize=8, alignment=2)),
                     Paragraph(f'<b><font color="#059669">{_money_str(total_amt)}</font></b>',
                               ParagraphStyle('ta', fontName=_PDF_FONT, fontSize=8, alignment=2)), '', 'TOTAL'])
        tbl = Table([head] + rows,
                    colWidths=[8 * mm, 17 * mm, 20 * mm, 20 * mm, 18 * mm, 24 * mm, 22 * mm, 49 * mm],
                    repeatRows=1)
        tbl.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#164e63')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), _PDF_FONT_B),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('FONTNAME', (0, 1), (-1, -1), _PDF_FONT),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('ALIGN', (4, 0), (4, -1), 'RIGHT'),
            ('ALIGN', (5, 0), (5, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, _PDF_LINE),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, _PDF_ZEBRA]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#ecfdf5')),
        ]))
        story.append(tbl)
    else:
        story.append(Paragraph('No rides recorded yet for this driver.',
                               ParagraphStyle('em', fontName=_PDF_FONT, fontSize=9, leading=13,
                                              textColor=_PDF_MUTED)))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    buf.seek(0)
    return buf


@app.route('/rides-finance/download')
def rides_finance_download():
    """Separate rides finance report: overall totals, driver-wise & monthly breakdowns."""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    denied = _require_admin_level()
    if denied:
        return denied

    data = _load_rides_overview()
    pdf_buf = _build_rides_finance_pdf(data['fin_rows'], data['monthly'], data['stats'], data['rf_totals'])
    fname = f"Rides_Finance_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    return send_file(pdf_buf, mimetype='application/pdf', as_attachment=True, download_name=fname)


def _build_rides_finance_pdf(fin_rows, monthly, stats, totals):
    total_amt = float(totals.get('total_rides') or 0)
    managed_amt = float(totals.get('managed') or 0)
    unmanaged_amt = float(totals.get('unmanaged') or 0)
    pct = round(managed_amt / total_amt * 100, 1) if total_amt else 0

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=18 * mm,
                            title='Rides Finance Report', author='PDM Rides Management')

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setStrokeColor(_PDF_LINE)
        canvas.setLineWidth(0.7)
        canvas.line(16 * mm, 13 * mm, A4[0] - 16 * mm, 13 * mm)
        canvas.setFont(_PDF_FONT, 7.5)
        canvas.setFillColor(_PDF_MUTED)
        canvas.drawString(16 * mm, 9 * mm, 'PDM â€¢ Rides Finance â€” system generated document')
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f'Page {doc_.page}')
        canvas.restoreState()

    story = []
    ref = f'RFN-{datetime.now().strftime("%Y%m%d%H%M")}'
    right_style = ParagraphStyle('r', fontName=_PDF_FONT, fontSize=8.5, leading=12, alignment=TA_RIGHT)
    band = Table([[
        [Paragraph('<font color="#86efac">PDM RIDES FINANCE</font>',
                   ParagraphStyle('k', fontName=_PDF_FONT_B, fontSize=8, leading=10)),
         Spacer(1, 4),
         Paragraph('<font color="white">Rides Finance Report</font>',
                   ParagraphStyle('t', fontName=_PDF_FONT_B, fontSize=17, leading=21))],
        [Paragraph(f'<font color="#bbf7d0">Report Ref</font><br/><font color="white"><b>#{ref}</b></font>', right_style),
         Spacer(1, 3),
         Paragraph(f'<font color="#bbf7d0">Generated</font><br/><font color="white">{datetime.now().strftime("%d %b %Y, %I:%M %p")}</font>', right_style)],
    ]], colWidths=[110 * mm, 68 * mm])
    band.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#14532d')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (0, 0), 12),
        ('RIGHTPADDING', (-1, -1), (-1, -1), 12),
        ('LINEBELOW', (0, 0), (-1, -1), 2.5, colors.HexColor('#22c55e')),
    ]))
    story += [band, Spacer(1, 8)]

    def cell(label, value_str, fg):
        return [
            Paragraph(label.replace('\n', '<br/>'),
                      ParagraphStyle('sl', fontName=_PDF_FONT_B, fontSize=7.5, leading=10, textColor=colors.HexColor('#64748b'))),
            Spacer(1, 3),
            Paragraph(f'<b><font color="{fg}">{value_str}</font></b>',
                      ParagraphStyle('sv', fontName=_PDF_FONT_B, fontSize=14, leading=17)),
        ]

    strip = Table([[
        cell('TOTAL RIDES AMOUNT\n(All time ride payouts recorded)', _money_str(total_amt), '#0f172a'),
        cell('MANAGED AMOUNT\n(Described)', _money_str(managed_amt), '#059669'),
        cell('UNMANAGED AMOUNT\n(Not described yet)', _money_str(unmanaged_amt),
             '#b91c1c' if unmanaged_amt > 0 else '#059669'),
    ]], colWidths=[59.3 * mm, 59.3 * mm, 59.3 * mm])
    strip.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor('#eef2ff')),
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor('#ecfdf5')),
        ('BACKGROUND', (2, 0), (2, 0), colors.HexColor('#fef2f2')),
        ('BOX', (0, 0), (-1, -1), 0.8, _PDF_LINE),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 9),
    ]))
    story += [_pdf_section('AMOUNT SUMMARY'), Spacer(1, 4), strip, Spacer(1, 4)]
    cov_color_txt = '#059669' if unmanaged_amt <= 0.005 else '#b91c1c'
    story.append(Paragraph(
        f'Described coverage: <b><font color="{cov_color_txt}">{pct}%</font></b>. '
        f'Unmanaged Amount = Total Rides Amount \u2212 Managed, and can never go below zero \u2014 '
        f'the system blocks any entry that would exceed the total ride payouts.',
        ParagraphStyle('cov', fontName=_PDF_FONT, fontSize=8.5, leading=12, textColor=colors.HexColor('#64748b'))))
    story.append(Spacer(1, 10))

    def summary_table(title, head, rows_, widths, name_head_width=None):
        out = [_pdf_section(title), Spacer(1, 4)]
        t = Table([head] + rows_, colWidths=widths, repeatRows=1)
        style = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#14532d')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), _PDF_FONT_B),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('FONTNAME', (0, 1), (-1, -1), _PDF_FONT),
            ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, _PDF_LINE),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, _PDF_ZEBRA]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]
        t.setStyle(TableStyle(style))
        out.append(t)
        return out

    if fin_rows:
        rows_ = [[r['driver'], str(r['rides']), f"{r['km']:,.1f}", _money_str(r['amount'])]
                 for r in fin_rows]
        rows_.append(['TOTAL',
                      str(sum(int(r['rides']) for r in fin_rows)),
                      f"{sum(float(r['km']) for r in fin_rows):,.1f}",
                      _money_str(sum(float(r['amount']) for r in fin_rows))])
        story += summary_table('DRIVER-WISE SUMMARY',
                               ['Driver', 'Rides', 'KM Driven', 'Total Amount'],
                               rows_, [70 * mm, 26 * mm, 36 * mm, 46 * mm])
        story.append(Spacer(1, 10))

    if monthly:
        rows_ = [[m['ym'], str(m['rides']), f"{m['km']:,.1f}", _money_str(m['amount'])]
                 for m in monthly]
        story += summary_table('MONTH-WISE SUMMARY',
                               ['Month', 'Rides', 'KM Driven', 'Total Amount'],
                               rows_, [70 * mm, 26 * mm, 36 * mm, 46 * mm])
    else:
        story.append(Paragraph('No ride transactions recorded yet.',
                               ParagraphStyle('em', fontName=_PDF_FONT, fontSize=9, leading=13,
                                              textColor=_PDF_MUTED)))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    buf.seek(0)
    return buf


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# --------------------------------------------------------------------------- #
#  Personal (self-service) PDF downloads for Room Renters and Drivers
# --------------------------------------------------------------------------- #


def _personal_pdf_response(fname, title, kicker, ref, info_pairs, table_title,
                           table_head, table_rows, col_widths, note=None):
    """Compact branded A4 PDF: info grid + one data table."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=18 * mm,
                            title=title, author='PDM Personal Data Management')

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setStrokeColor(_PDF_LINE)
        canvas.setLineWidth(0.7)
        canvas.line(16 * mm, 13 * mm, A4[0] - 16 * mm, 13 * mm)
        canvas.setFont(_PDF_FONT, 7.5)
        canvas.setFillColor(_PDF_MUTED)
        canvas.drawString(16 * mm, 9 * mm, 'PDM \u2022 system generated document')
        canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f'Page {doc_.page}')
        canvas.restoreState()

    story = []
    head_left = [
        Paragraph(f'<font color="#a5b4fc">{kicker}</font>',
                  ParagraphStyle('k', fontName=_PDF_FONT_B, fontSize=8, leading=10)),
        Spacer(1, 4),
        Paragraph(f'<font color="white">{title}</font>',
                  ParagraphStyle('t', fontName=_PDF_FONT_B, fontSize=17, leading=21)),
    ]
    right_style = ParagraphStyle('r', fontName=_PDF_FONT, fontSize=8.5, leading=12, alignment=TA_RIGHT)
    gen_stamp = datetime.now().strftime('%d %b %Y, %I:%M %p')
    head_right = [
        Paragraph(f'<font color="#c7d2fe">Reference</font><br/><font color="white"><b>{ref}</b></font>', right_style),
        Spacer(1, 4),
        Paragraph(f'<font color="#c7d2fe">Generated On</font><br/><font color="white"><b>{gen_stamp}</b></font>', right_style),
    ]
    head = Table([[head_left, head_right]], colWidths=[110 * mm, 68 * mm])
    head.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#111827')),
        ('BOX', (0, 0), (-1, -1), 0.8, _PDF_LINE),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
    ]))
    story += [head, Spacer(1, 12)]

    lbl_st = ParagraphStyle('lbl', fontName=_PDF_FONT_B, fontSize=7.6, leading=10, textColor=colors.HexColor('#64748b'))
    val_st = ParagraphStyle('val', fontName=_PDF_FONT, fontSize=9.3, leading=12.5, textColor=colors.HexColor('#0f172a'))
    info_cells = []
    row_buf = []
    for label, value in info_pairs:
        row_buf.append([Paragraph(str(label).upper(), lbl_st), Spacer(1, 2), Paragraph(str(value or '\u2014'), val_st)])
        if len(row_buf) == 4:
            info_cells.append(row_buf)
            row_buf = []
    if row_buf:
        while len(row_buf) < 4:
            row_buf.append('')
        info_cells.append(row_buf)
    info_tbl = Table(info_cells, colWidths=[44.5 * mm] * 4)
    info_tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f8fafc')),
        ('BOX', (0, 0), (-1, -1), 0.8, _PDF_LINE),
        ('GRID', (0, 0), (-1, -1), 0.4, _PDF_LINE),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story += [_pdf_section('PERSONAL DETAILS'), Spacer(1, 4), info_tbl, Spacer(1, 14)]

    head_st = ParagraphStyle('th', fontName=_PDF_FONT_B, fontSize=8, leading=10, textColor=colors.white)
    cell_st = ParagraphStyle('td', fontName=_PDF_FONT, fontSize=8.6, leading=11.5)
    data = [[Paragraph(f'{h}', head_st) for h in table_head]]
    for r_ in table_rows:
        data.append([Paragraph(str(c_), cell_st) for c_ in r_])
    body = Table(data, colWidths=col_widths, repeatRows=1)
    body.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
        ('GRID', (0, 0), (-1, -1), 0.4, _PDF_LINE),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story += [_pdf_section(table_title), Spacer(1, 4), body]
    if note:
        story += [Spacer(1, 8),
                  Paragraph(note, ParagraphStyle('nt', fontName=_PDF_FONT_B, fontSize=9, leading=13,
                                                 textColor=colors.HexColor('#059669')))]

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    buf.seek(0)
    return send_file(buf, mimetype='application/pdf', as_attachment=True, download_name=fname)


def _renter_own_record(cursor):
    cursor.execute("""
        SELECT r.id, u.firstname, u.lastname, u.email, u.phone, u.gender,
               r.aadharno, r.panno, r.floortype, r.aadhar_address, r.occupation,
               r.total_member, r.rental_joiningdate
        FROM rentaldetails r JOIN users u ON u.id = r.userid
        WHERE r.userid = %s
        ORDER BY r.created_at DESC LIMIT 1
    """, (session['user_id'],))
    return cursor.fetchone()


@app.route('/my/details-pdf')
def my_details_pdf():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    me_t = _get_current_user_type()
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()

        if me_t == _rid('Room Renter'):
            rec = _renter_own_record(cursor)
            cursor.close()
            if not rec:
                flash('No tenancy record found for your account yet.', 'info')
                return redirect(url_for('rental_management'))
            name = f"{rec['firstname']} {rec['lastname']}".strip()
            pairs = [
                ('Name', name), ('Email', rec['email']), ('Phone', rec['phone']),
                ('Gender', rec['gender']),
                ('Aadhaar No', rec['aadharno']), ('PAN No', rec['panno'] or '\u2014'),
                ('Floor / Unit', rec['floortype'] or '\u2014'), ('Occupation', rec['occupation'] or '\u2014'),
                ('Total Members', rec['total_member']),
                ('Joining Date', rec['rental_joiningdate'].strftime('%d %b %Y') if rec['rental_joiningdate'] else '\u2014'),
                ('Address', rec['aadhar_address'] or '\u2014'), ('Record ID', f"#TNT-{rec['id']:04d}"),
            ]
            cursor.close()
            return _personal_pdf_response(
                f'My_Details_{name.replace(" ", "_")}.pdf',
                f'Personal Details \u2014 {name}', 'PDM RENTAL MANAGEMENT', '#ME-DET',
                pairs, 'TENANCY SUMMARY',
                ['Field', 'Value'],
                [('Tenancy Status', 'Active room renter'),
                 ('Registered On', datetime.now().strftime('%d %b %Y'))],
                [60 * mm, 118 * mm])

        if me_t == _rid('Driver'):
            cursor.execute("""
                SELECT d.id, u.firstname, u.lastname, u.email, u.phone, u.gender,
                       d.aadharno, d.license_no, d.vehicle_no, d.alt_phone, d.address, d.joiningdate
                FROM drivers d JOIN users u ON u.id = d.userid
                WHERE d.userid = %s ORDER BY d.created_at DESC LIMIT 1
            """, (session['user_id'],))
            rec = cursor.fetchone()
            cursor.close()
            if not rec:
                flash('No driver profile found for your account yet.', 'info')
                return redirect(url_for('rides_management'))
            name = f"{rec['firstname']} {rec['lastname']}".strip()
            pairs = [
                ('Name', name), ('Email', rec['email']), ('Phone', rec['phone']),
                ('Gender', rec['gender']),
                ('Aadhaar No', rec['aadharno']), ('Licence No', rec['license_no']),
                ('Vehicle No', rec['vehicle_no'] or '\u2014'), ('Alt Phone', rec['alt_phone'] or '\u2014'),
                ('Joining Date', rec['joiningdate'].strftime('%d %b %Y') if rec['joiningdate'] else '\u2014'),
                ('Driver ID', f"#DRV-{rec['id']:04d}"), ('Address', rec['address'] or '\u2014'), ('Status', 'Active driver'),
            ]
            return _personal_pdf_response(
                f'My_Details_{name.replace(" ", "_")}.pdf',
                f'Personal Details \u2014 {name}', 'PDM RIDES MANAGEMENT', '#ME-DET',
                pairs, 'DRIVER SUMMARY',
                ['Field', 'Value'],
                [('Employment', 'Rides \u2014 daily basis'),
                 ('Registered On', datetime.now().strftime('%d %b %Y'))],
                [60 * mm, 118 * mm])

        flash('Personal details download is available for Room Renters and Drivers.', 'info')
        return redirect(url_for('dashboard'))
    except Exception:
        app.logger.exception('my_details_pdf failed')
        flash('Could not generate the PDF. Please try again.', 'danger')
        return redirect(url_for('dashboard'))
    finally:
        if conn:
            conn.close()


@app.route('/my/rent-pdf')
def my_rent_pdf():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    me_t = _get_current_user_type()
    if me_t not in (_rid('Room Renter'), _rid('Master Admin'), _rid('Admin')):
        flash('You do not have permission to download this file.', 'danger')
        return redirect(url_for('dashboard'))
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        rec = _renter_own_record(cursor)
        if not rec:
            flash('No tenancy record found for your account yet.', 'info')
            return redirect(url_for('rental_management'))
        cursor.execute("""
            SELECT rd.year, rd.month, rd.rentamount::float AS rentamount, rd.currentdate
            FROM rentdetails rd
            WHERE rd.rentalid = %s
            ORDER BY rd.year DESC, rd.month DESC, rd.id DESC
        """, (rec['id'],))
        pays = cursor.fetchall()
        cursor.close()
        total = sum(float(p['rentamount']) for p in pays)

        def sort_key(p):
            return (p['currentdate'].strftime('%d %b %Y, %I:%M %p')
                    if p.get('currentdate') else '\u2014')

        rows = []
        for i, p in enumerate(pays, 1):
            rows.append((
                str(i), str(p['year']),                 _MONTH_NAMES[int(p['month']) - 1]
                if p['month'] and 1 <= int(p['month']) <= 12 else str(p['month']),
                f'\u20b9 {float(p["rentamount"]):,.2f}',
                p['currentdate'].strftime('%d %b %Y') if p['currentdate'] else '\u2014',
            ))
        name = f"{rec['firstname']} {rec['lastname']}".strip()
        note = f'Total Rent Paid: \u20b9 {total:,.2f} across {len(pays)} payment(s).' if pays else None
        return _personal_pdf_response(
            f'My_Rent_Payments_{name.replace(" ", "_")}.pdf',
            f'Rent Payment Ledger \u2014 {name}', 'PDM RENTAL MANAGEMENT', '#ME-RENT',
            [
                ('Name', name), ('Unit / Floor', rec['floortype'] or '\u2014'),
                ('Aadhaar No', rec['aadharno']),
                ('Payments Count', len(pays)),
            ],
            'RENT PAYMENT HISTORY',
            ['#', 'Year', 'Month', 'Amount Paid', 'Paid On'],
            rows or [('-', '-', '-', '-', '-')],
            [12 * mm, 22 * mm, 42 * mm, 48 * mm, 54 * mm],
            note)
    except Exception:
        app.logger.exception('my_rent_pdf failed')
        flash('Could not generate the PDF. Please try again.', 'danger')
        return redirect(url_for('rental_management'))
    finally:
        if conn:
            conn.close()


@app.route('/my/rides-pdf')
def my_rides_pdf():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    me_t = _get_current_user_type()
    if me_t not in (_rid('Driver'), _rid('Master Admin'), _rid('Admin')):
        flash('You do not have permission to download this file.', 'danger')
        return redirect(url_for('dashboard'))
    conn = None
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT d.id, u.firstname, u.lastname, d.vehicle_no FROM drivers d
            JOIN users u ON u.id = d.userid WHERE d.userid = %s
            ORDER BY d.created_at DESC LIMIT 1
        """, (session['user_id'],))
        rec = cursor.fetchone()
        if not rec:
            flash('No driver profile found for your account yet.', 'info')
            return redirect(url_for('rides_management'))
        cursor.execute("""
            SELECT ride_date, km_driven::float AS km_driven,
                   meter_start::float AS meter_start, meter_end::float AS meter_end,
                   amount::float AS amount
            FROM ridedetails WHERE driverid = %s
            ORDER BY ride_date DESC, id DESC
        """, (rec['id'],))
        rides = cursor.fetchall()
        cursor.close()
        total_amt = sum(float(r_['amount']) for r_ in rides)
        total_km = sum(float(r_['km_driven']) for r_ in rides)

        rows = []
        for i, r_ in enumerate(rides, 1):
            rows.append((
                str(i),
                r_['ride_date'].strftime('%d %b %Y') if r_['ride_date'] else '\u2014',
                f"{float(r_['km_driven']):,.1f}",
                f"{r_['meter_start']:,.0f} \u2192 {r_['meter_end']:,.0f}"
                if r_['meter_start'] is not None and r_['meter_end'] is not None else '\u2014',
                f"\u20b9 {float(r_['amount']):,.2f}",
            ))
        name = f"{rec['firstname']} {rec['lastname']}".strip()
        note = (f"Total: {len(rides)} ride(s) \u2022 {total_km:,.1f} km \u2022 \u20b9 {total_amt:,.2f}."
                if rides else None)
        return _personal_pdf_response(
            f'My_Rides_{name.replace(" ", "_")}.pdf',
            f'Daily Ride Ledger \u2014 {name}', 'PDM RIDES MANAGEMENT', '#ME-RIDE',
            [
                ('Name', name), ('Vehicle No', rec['vehicle_no'] or '\u2014'),
                ('Rides Recorded', len(rides)), ('Total KM', f'{total_km:,.1f} km'),
            ],
            'DAILY RIDES HISTORY',
            ['#', 'Date', 'KM Driven', 'Meter Reading', 'Amount'],
            rows or [('-', '-', '-', '-', '-')],
            [12 * mm, 34 * mm, 30 * mm, 52 * mm, 50 * mm],
            note)
    except Exception:
        app.logger.exception('my_rides_pdf failed')
        flash('Could not generate the PDF. Please try again.', 'danger')
        return redirect(url_for('rides_management'))
    finally:
        if conn:
            conn.close()


if __name__ == '__main__':
    app.run(debug=True, port=5000)
