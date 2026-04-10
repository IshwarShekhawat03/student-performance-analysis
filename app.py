import streamlit as st
import sqlite3
import random
import datetime
import time
from twilio.rest import Client
import os


    
import json 
import hashlib
import hmac
import pandas as pd
import streamlit.components.v1 as components


# ===================== CONFIG =====================
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
ADMIN_NUMBER = "+910000000000"
TWILIO_NUMBER = "+10000000000"
SMS_PREFIX = "📲 EasyPay Alert: "

# ===================== DATABASE SETUP =====================
conn = sqlite3.connect("atm_users.db", check_same_thread=False)
cursor = conn.cursor()

def ensure_users_schema():
    # Ensure users table has exactly the expected 4 columns.
    cursor.execute("PRAGMA table_info(users)")
    cols = [row[1] for row in cursor.fetchall()]
    expected_cols = ["username", "pin", "balance", "contact"]
    if set(cols) != set(expected_cols):
        # Recreate users table with the expected schema
        cursor.execute("DROP TABLE IF EXISTS users")
        cursor.execute("""
            CREATE TABLE users (
                username TEXT PRIMARY KEY,
                pin TEXT,
                balance REAL,
                contact TEXT
            )
        """)
        conn.commit()

ensure_users_schema()

# Create transactions table (if missing)
cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    time TEXT,
    type TEXT,
    amount REAL,
    balance_after REAL
)
""")
conn.commit() 

# ===================== VOICE SYSTEM (ADD-ON) =====================
def speak(text):
    components.html(
        f"""
        <script>
        var msg = new SpeechSynthesisUtterance("{text}");
        msg.rate = 1;
        msg.pitch = 1;
        msg.volume = 1;
        window.speechSynthesis.speak(msg);
        </script>
        """,
        height=0,
    )


# Create sms_logs table to record SMS send attempts/results
cursor.execute("""
CREATE TABLE IF NOT EXISTS sms_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT,
    to_number TEXT,
    message TEXT,
    status TEXT
)
""")
conn.commit()

# ===================== SMS (Twilio) helpers =====================
def log_sms(to_number, message, status):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO sms_logs (time, to_number, message, status) VALUES (?, ?, ?, ?)",
        (ts, to_number, message, status)
    )
    conn.commit()
 
def send_sms(to_number, message_text):
    """Send SMS via Twilio. Returns True if sent, False otherwise.
       Also logs the attempt in sms_logs table.
    """
    full = f"{SMS_PREFIX}{message_text}"
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(body=full, from_=TWILIO_NUMBER, to=to_number)
        log_sms(to_number, full, "SENT")
        return True
    except Exception as e:
        # Log the failure but don't raise — app must remain usable
        log_sms(to_number, full, f"FAILED: {e}")
        return False

def notify_admin(message_text):
    send_sms(ADMIN_NUMBER, message_text)

# ===================== TRANSACTION / LOGGING =====================
def log_transaction(username, t_type, amount, balance_after):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(                 
        "INSERT INTO transactions (username, time, type, amount, balance_after) VALUES (?, ?, ?, ?, ?)",
        (username, ts, t_type, amount, balance_after)
    )
    conn.commit()

# ===================== SESSION / OTP / Timeout =====================
def update_activity():
    st.session_state['last_activity'] = time.time()

def check_auto_logout():
    if 'last_activity' in st.session_state and st.session_state.get('authenticated'):
        if time.time() - st.session_state['last_activity'] > 300:  # 5 minutes
            st.warning("Session expired due to inactivity.")
            # keep session_state minimal and go to home
            st.session_state.clear()
            st.session_state.page = "home"
            st.rerun()

def generate_otp():
    return str(random.randint(100000, 999999))

def is_otp_valid():
    if 'otp_timestamp' not in st.session_state:
        return False
    return (time.time() - st.session_state['otp_timestamp']) <= 60  # 1 minute expiry

# ===================== ADMIN CREDENTIALS (local file) =====================
ADMIN_CREDS_FILE = ".admin_creds"
OWNER_SYS_USER = "Hp World"   # system username that can see admin option
PBKDF2_ITERATIONS = 200_000
DKLEN = 32
HASH_NAME = "sha256"

def _derive_key(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(HASH_NAME, password.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=DKLEN)

def load_admin_creds():
    if not os.path.exists(ADMIN_CREDS_FILE):
        salt = os.urandom(16)
        dk = _derive_key("iss@paisa", salt)   # default admin password
        with open(ADMIN_CREDS_FILE, "w") as f:
            json.dump({
                "username": "iss@bank",
                "salt_hex": salt.hex(),
                "dk_hex": dk.hex()
            }, f)
    with open(ADMIN_CREDS_FILE, "r") as f:
        return json.load(f)

def verify_admin_credentials(username, password):
    payload = load_admin_creds()
    if not payload:
        return False
    if username != payload.get("username"):
        return False
    salt = bytes.fromhex(payload["salt_hex"])
    dk_expected = bytes.fromhex(payload["dk_hex"])
    dk_candidate = _derive_key(password, salt)
    return hmac.compare_digest(dk_expected, dk_candidate)

# ===================== PAGE CONTROL =====================
if 'page' not in st.session_state:
    st.session_state.page = "home"

check_auto_logout()

try:
    current_user = os.getlogin()
except Exception:
    current_user = ""
is_owner_system = (current_user == OWNER_SYS_USER)

# ===================== HOME PAGE =====================
if st.session_state.page == "home":
    st.title("🏦 EasyPay ATM")
    menu_options = ["Register", "Login", "Exit"]
    if is_owner_system:
        menu_options = ["Register", "Login", "Admin Login", "Exit"]
    menu = st.sidebar.radio("Menu", menu_options)

    # ---------- REGISTER ----------
    if menu == "Register":
        st.subheader("🧾 Create New Account")
        username = st.text_input("Enter Username")
        pin = st.text_input("Enter 4-digit PIN", type="password")
        balance = st.number_input("Initial Balance", min_value=0.0, format="%.2f")
        contact = st.text_input("Enter Mobile Number (+91XXXXXXXXXX)")
        if st.button("Register"):
            if not username or not pin or not contact:
                st.warning("Please fill all fields.")
                notify_admin(f"⚠️ Registration failed (missing fields) for username: {username}")
            else:
                cursor.execute("SELECT username FROM users WHERE username=?", (username,))
                if cursor.fetchone():
                    st.error("Username already exists.")
                    notify_admin(f"⚠️ Registration attempt failed - username exists: {username}")
                else:
                    cursor.execute(
                        "INSERT INTO users (username, pin, balance, contact) VALUES (?, ?, ?, ?)",
                        (username, pin, float(balance), contact)
                    )
                    conn.commit()
                    log_transaction(username, "Account Created", float(balance), float(balance))
                    # send SMS to user and admin (if SMS fails, continue)
                    sent = send_sms(contact, f"Your EasyPay account has been created. Balance ₹{float(balance):.2f}")
                    notify_admin(f"✅ New account created: {username}. Balance ₹{float(balance):.2f}. SMS sent: {sent}")
                    st.success("Account created successfully ✅")

    # ---------- LOGIN ----------
    elif menu == "Login":
        st.subheader("🔐 Login (OTP)")
        username = st.text_input("Enter Username")
        pin = st.text_input("Enter PIN", type="password")
        if st.button("Login"):
            cursor.execute("SELECT contact FROM users WHERE username=? AND pin=?", (username, pin))
            row = cursor.fetchone()
            if row:
                contact_number = row[0]
                otp = generate_otp()
                st.session_state['otp'] = otp
                st.session_state['otp_timestamp'] = time.time()
                st.session_state['logged_in_user'] = username
                st.session_state['contact_number'] = contact_number
                sent = send_sms(contact_number, f"Your OTP for EasyPay login is {otp}")
                if not sent:
                    # fallback for trial Twilio -> show OTP in-app for testing
                    st.warning(f"OTP SMS failed to send. Use in-app OTP: {otp}")
                notify_admin(f"OTP {'sent' if sent else 'failed to send'} to {username} ({contact_number}) for login.")
            else:
                st.error("Invalid username or PIN.")
                notify_admin(f"❌ Failed login attempt for username: {username}")

        if 'otp' in st.session_state:
            entered_otp = st.text_input("Enter OTP")
            if st.button("Verify OTP"):
                if is_otp_valid() and entered_otp == st.session_state['otp']:
                    st.success("Login successful ✅")
                    st.session_state['authenticated'] = True
                    st.session_state.page = "dashboard"
                    update_activity()
                    notify_admin(f"✅ User {st.session_state.get('logged_in_user')} logged in.")
                    st.rerun()
                elif not is_otp_valid(): 
                    st.error("OTP expired ❌")
                    notify_admin(f"⚠️ OTP expired for user {st.session_state.get('logged_in_user')}")
                else:
                    st.error("Invalid OTP ❌")
                    notify_admin(f"❌ Invalid OTP attempt for user {st.session_state.get('logged_in_user')}")

    # ---------- ADMIN LOGIN ----------
    elif menu == "Admin Login" and is_owner_system:
        st.subheader("🛡️ Admin Login")
        admin_user = st.text_input("Admin Username")
        admin_pass = st.text_input("Admin Password", type="password")
        if st.button("Login as Admin"):
            if verify_admin_credentials(admin_user, admin_pass):
                st.session_state['admin_authenticated'] = True
                st.session_state.page = "admin_dashboard"
                notify_admin("🛡️ Admin logged in successfully.")
                st.success("Welcome Admin ✅")
                st.rerun()
            else:
                st.error("Invalid admin credentials.")
                notify_admin("❌ Failed admin login attempt.")

    elif menu == "Exit":
        st.info("👋 Thank you for using EasyPay")

# ===================== USER DASHBOARD =====================
elif st.session_state.page == "dashboard":
    update_activity()
    username = st.session_state.get('logged_in_user')
    if not username:
        st.error("No logged in user. Please login again.")
        st.session_state.clear()
        st.session_state.page = "home"
        st.rerun()

    st.sidebar.title("🏧 EasyPay Operations")
    choice = st.sidebar.radio("Select", ["Welcome", "Check Balance", "Deposit", "Withdraw", "Transfer Money", "Change PIN", "Transaction History", "Logout"])

    cursor.execute("SELECT balance, contact, pin FROM users WHERE username=?", (username,))
    row = cursor.fetchone()
    if not row:
        st.error("User not found. Please login again.")
        st.session_state.clear() 
        st.session_state.page = "home"
        st.rerun()  
    balance, contact_number, old_pin = row
    balance = float(balance)  # ensure float
 
    if choice == "Welcome":
        st.subheader(f"👋 Welcome, {username}!")
        st.info("Use the sidebar to access ATM functions.")
        update_activity() 

    elif choice == "Check Balance":
        st.subheader("💰 Your Current Balance")
        st.info(f"Balance ₹{balance:.2f}")
        notify_admin(f"ℹ️ {username} checked balance: ₹{balance:.2f}")
        update_activity()
        speak(f"current balance.  {int(balance)}")

    elif choice == "Deposit":
        st.subheader("💵 Deposit Money")
        amount = st.number_input("Enter Amount", min_value=0.0, format="%.2f")
        if st.button("Deposit"):
            if float(amount) <= 0:  
                st.warning("Enter a positive amount.")
            else:
                cursor.execute("UPDATE users SET balance = balance + ? WHERE username=?", (float(amount), username))
                conn.commit()
                balance += float(amount)
                log_transaction(username, "Deposit", float(amount), balance)
                sent = send_sms(contact_number, f"You deposited ₹{float(amount):.2f}. New balance ₹{balance:.2f}")
                notify_admin(f"💰 {username} deposited ₹{float(amount):.2f}. New balance ₹{balance: .2f}. SMS sent={sent}")
                st.success(f"Deposited ₹{float(amount):.2f} successfully ✅")
                speak(f"Deposit successful. Amount rupees {int(amount)}")
            update_activity()
    
    elif choice == "Withdraw":
        st.subheader("💸 Withdraw Money")
        amount = st.number_input("Enter Amount", min_value=0.0, format="%.2f")
        if st.button("Withdraw"):
            if float(amount) <= 0: 
                st.warning("Enter a positive amount.")
            elif float(amount) > balance:
                st.error("Insufficient balance ❌")
                notify_admin(f"⚠️ {username} attempted withdrawal ₹{float(amount):.2f} but had {balance:.2f}")
            else:
                cursor.execute("UPDATE users SET balance = balance - ? WHERE username=?", (float(amount), username))
                conn.commit()
                balance -= float(amount)
                log_transaction(username, "Withdraw", float(amount), balance)
                sent = send_sms(contact_number, f"You withdrew ₹{float(amount):.2f}. Remaining balance ₹{balance:.2f}")
                notify_admin(f"💸 {username} withdrew ₹{float(amount):.2f}. New balance ₹{balance:.2f}. SMS sent={sent}")
                st.success(f"Withdrawn ₹{float(amount):.2f} successfully ✅")
                speak(f"Withdrawal successful. Amount rupees {int(amount)}")
            update_activity()

    elif choice == "Transfer Money":
        st.subheader("🏦 Transfer Money (to another registered user)")
        receiver = st.text_input("Recipient username")
        transfer_amount = st.number_input("Amount to transfer", min_value=1.0, format="%.2f")
        if st.button("Transfer"):
            try:
                if not receiver:
                    st.error("Enter recipient username.")
                elif receiver == username:
                    st.error("Cannot transfer to yourself.")
                else:
                    # Fetch receiver data
                    cursor.execute("SELECT balance, contact FROM users WHERE username=?", (receiver,))
                    recv = cursor.fetchone()
                    if not recv:
                        st.error("Recipient not found.")
                    else:
                        recv_balance, recv_contact = float(recv[0]), recv[1]
                        transfer_amount = float(transfer_amount)
                        if transfer_amount <= 0:
                            st.warning("Enter an amount greater than 0.")
                        elif transfer_amount > balance:
                            st.error("Insufficient funds.")
                            notify_admin(f"⚠️ {username} attempted transfer ₹{transfer_amount:.2f} -> {receiver} but insufficient funds (has ₹{balance:.2f}).")
                        else:
                            # Atomic transfer using transaction
                            try:
                                conn.execute("BEGIN")
                                cursor.execute("UPDATE users SET balance = balance - ? WHERE username=?", (transfer_amount, username))
                                cursor.execute("UPDATE users SET balance = balance + ? WHERE username=?", (transfer_amount, receiver))
                                conn.commit()
                            except Exception as e:
                                conn.rollback()
                                st.error("Transfer failed (DB error).")
                                notify_admin(f"❌ Transfer DB error: {e}")
                                raise

                            # update local sender balance var
                            balance -= transfer_amount

                            # log both transactions
                            log_transaction(username, "Transfer Sent", transfer_amount, balance)
                            cursor.execute("SELECT balance FROM users WHERE username=?", (receiver,))
                            new_recv_balance = float(cursor.fetchone()[0])
                            log_transaction(receiver, "Transfer Received", transfer_amount, new_recv_balance)

                            # SMS to both (if fails, still continue)
                            sent_sender = send_sms(contact_number, f"You sent ₹{transfer_amount:.2f} to {receiver}. New balance ₹{balance:.2f}")
                            sent_recv = send_sms(recv_contact, f"You received ₹{transfer_amount:.2f} from {username}. New balance ₹{new_recv_balance:.2f}")
                            notify_admin(f"🔁 {username} -> {receiver} ₹{transfer_amount:.2f}. Sender SMS={sent_sender}, Receiver SMS={sent_recv}")
                            st.success(f"Transferred ₹{transfer_amount:.2f} to {receiver} ✅")
                            speak(f"Transfer successful. Rupees {int(transfer_amount)} sent to {receiver}")

            finally:
                update_activity()

    elif choice == "Change PIN":
        st.subheader("🔑 Change PIN")
        new_pin = st.text_input("Enter new PIN", type="password")
        confirm_pin = st.text_input("Confirm new PIN", type="password")
        if st.button("Update PIN"):
            if len(new_pin) != 4 or not new_pin.isdigit():
                st.warning("PIN must be 4 digits.")
            elif new_pin == old_pin:
                st.warning("New PIN must be different.")
            elif new_pin != confirm_pin:
                st.error("PIN mismatch.")
            else:
                cursor.execute("UPDATE users SET pin=? WHERE username=?", (new_pin, username))
                conn.commit()
                send_sms(contact_number, "Your EasyPay PIN has been changed successfully.")
                notify_admin(f"🔑 {username} changed PIN.")
                st.success("PIN updated ✅")
                speak("Your PIN has been changed successfully")
            update_activity()

    elif choice == "Transaction History":
        st.subheader("📜 Transaction History (all)")
        cursor.execute("SELECT time, type, amount, balance_after FROM transactions WHERE username=? ORDER BY id DESC", (username,))
        rows = cursor.fetchall()
        if rows:
            df = pd.DataFrame(rows, columns=["Time", "Type", "Amount", "Balance After"])
            st.table(df)
        else:
            st.info("No transactions yet.")
        update_activity()

    elif choice == "Logout":
        notify_admin(f"🚪 {username} logged out.")
        st.session_state.clear()
        st.session_state.page = "home"
        st.success("Logged out ✅")
        speak("You have logged out successfully")
        st.rerun()

# ===================== ADMIN DASHBOARD =====================
elif st.session_state.page == "admin_dashboard" and st.session_state.get("admin_authenticated"):
    update_activity()
    st.title("🛡️ Admin Dashboard")
    admin_choice = st.sidebar.radio("Admin Menu", ["Overview", "All Users", "Transaction Summary", "SMS Logs", "Logout"])

    if admin_choice == "Overview":
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(balance),0) FROM users")
        total_users, total_balance = cursor.fetchone()
        cursor.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='Deposit'")
        total_deposit = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type='Withdraw'")
        total_withdraw = cursor.fetchone()[0] or 0
        st.metric("Total Users", total_users)
        st.metric("Total Deposits", f"₹{float(total_deposit):.2f}")
        st.metric("Total Withdrawals", f"₹{float(total_withdraw):.2f}")
        st.metric("Total Balance", f"₹{float(total_balance):.2f}")
        notify_admin("📊 Admin viewed Overview.")

    elif admin_choice == "All Users":
        cursor.execute("SELECT username, pin, balance, contact FROM users")
        rows = cursor.fetchall()
        if rows:
            df = pd.DataFrame(rows, columns=["Username", "PIN", "Balance", "Contact"])
            st.table(df)
        else:
            st.info("No users found.")
        notify_admin("📋 Admin viewed All Users.")

    elif admin_choice == "Transaction Summary":
        cursor.execute("SELECT username, time, type, amount, balance_after FROM transactions ORDER BY id DESC")
        rows = cursor.fetchall()
        if rows:
            df = pd.DataFrame(rows, columns=["Username", "Time", "Type", "Amount", "Balance After"])
            st.table(df)
        else:
            st.info("No transactions found.")
        notify_admin("📜 Admin viewed Transaction Summary.")

    elif admin_choice == "SMS Logs":
        st.subheader("📩 SMS Logs")
        cursor.execute("SELECT id, time, to_number, message, status FROM sms_logs ORDER BY id DESC")
        logs = cursor.fetchall()
        if logs:
            df = pd.DataFrame(logs, columns=["ID", "Time", "To", "Message", "Status"])
            st.table(df)
        else:
            st.info("No SMS logs yet.")
        notify_admin("📨 Admin viewed SMS logs.")

    elif admin_choice == "Logout":
        notify_admin("🚪 Admin logged out.")
        st.session_state.clear()
        st.session_state.page = "home" 
        st.success("Admin logged out ✅")
        speak("Admin logged out successfully")
        st.rerun()
