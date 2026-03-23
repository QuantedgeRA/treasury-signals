"""
auth.py — Authentication & Access Control
-------------------------------------------
Simple, secure authentication for the Streamlit dashboard.
Uses the existing subscribers table with a password_hash column.

Public pages: Home (landing page)
Protected pages: Everything else (requires login)

Usage in dashboard.py:
    from auth import require_auth, show_login_page, logout

    # At the top of any protected page:
    subscriber = require_auth()
    if not subscriber:
        show_login_page()
        st.stop()

    # subscriber is now the full profile dict
"""

import os
import hashlib
import secrets
import streamlit as st
from datetime import datetime
from dotenv import load_dotenv
from supabase import create_client
from logger import get_logger

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


# ============================================
# SQL — Add password column to subscribers
# ============================================

SETUP_SQL = """
-- Add password_hash column to existing subscribers table
ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS password_hash TEXT DEFAULT '';
"""


# ============================================
# PASSWORD HASHING
# ============================================

def _hash_password(password, salt=None):
    """Hash a password with a salt using SHA-256."""
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}:{hashed}"


def _verify_password(password, stored_hash):
    """Verify a password against a stored hash."""
    if not stored_hash or ":" not in stored_hash:
        return False
    salt = stored_hash.split(":")[0]
    return _hash_password(password, salt) == stored_hash


# ============================================
# AUTH FUNCTIONS
# ============================================

def register_user(name, email, password, company_name, ticker="", sector="",
                  country="", role="", btc_holdings=0, avg_purchase_price=0,
                  total_invested_usd=0):
    """
    Register a new user (creates subscriber + sets password).
    Returns the subscriber profile or None.
    """
    try:
        # Check if email already exists
        existing = supabase.table("subscribers").select("email").eq("email", email.lower().strip()).execute()
        if existing.data:
            logger.warning(f"Registration failed: {email} already exists")
            return None

        password_hash = _hash_password(password)
        subscriber_id = f"sub_{email.split('@')[0]}_{datetime.now().strftime('%Y%m%d')}"

        import json
        row = {
            "subscriber_id": subscriber_id,
            "name": name,
            "email": email.lower().strip(),
            "role": role,
            "company_name": company_name,
            "ticker": ticker.upper().strip() if ticker else "",
            "sector": sector,
            "country": country,
            "btc_holdings": btc_holdings,
            "avg_purchase_price": avg_purchase_price,
            "total_invested_usd": total_invested_usd,
            "plan": "pro",
            "password_hash": password_hash,
            "watchlist_json": json.dumps([]),
        }

        supabase.table("subscribers").insert(row).execute()
        logger.info(f"User registered: {name} ({company_name}) — {email}")

        return get_user_by_email(email)

    except Exception as e:
        logger.error(f"Registration failed for {email}: {e}", exc_info=True)
        return None


def set_password(email, password):
    """Set or update a password for an existing subscriber."""
    try:
        password_hash = _hash_password(password)
        supabase.table("subscribers").update({
            "password_hash": password_hash,
        }).eq("email", email.lower().strip()).execute()
        logger.info(f"Password set for {email}")
        return True
    except Exception as e:
        logger.error(f"Failed to set password for {email}: {e}", exc_info=True)
        return False


def authenticate(email, password):
    """
    Authenticate a user by email and password.
    Returns the subscriber profile or None.
    """
    try:
        result = supabase.table("subscribers").select("*").eq("email", email.lower().strip()).limit(1).execute()
        if not result.data:
            return None

        user = result.data[0]
        stored_hash = user.get("password_hash", "")

        # If no password set, allow login with any password (migration period)
        # and set the password for future logins
        if not stored_hash:
            logger.info(f"First login for {email} — setting password")
            set_password(email, password)
            return _enrich_profile(user)

        if _verify_password(password, stored_hash):
            # Update last_active
            try:
                supabase.table("subscribers").update({
                    "last_active": datetime.now().isoformat(),
                }).eq("email", email.lower().strip()).execute()
            except Exception:
                pass
            return _enrich_profile(user)

        return None

    except Exception as e:
        logger.error(f"Authentication failed for {email}: {e}", exc_info=True)
        return None


def get_user_by_email(email):
    """Get a user profile by email."""
    try:
        result = supabase.table("subscribers").select("*").eq("email", email.lower().strip()).limit(1).execute()
        if result.data:
            return _enrich_profile(result.data[0])
        return None
    except Exception as e:
        logger.error(f"Failed to fetch user {email}: {e}", exc_info=True)
        return None


def _enrich_profile(user):
    """Add computed fields to a user profile."""
    import json
    user["watchlist"] = json.loads(user.get("watchlist_json", "[]")) if user.get("watchlist_json") else []
    return user


# ============================================
# STREAMLIT SESSION HELPERS
# ============================================

def require_auth():
    """
    Check if the user is authenticated.
    Returns the subscriber profile if logged in, None if not.
    """
    if "authenticated" in st.session_state and st.session_state["authenticated"]:
        return st.session_state.get("subscriber_profile")
    return None


def login_user(profile):
    """Store authenticated user in session state."""
    st.session_state["authenticated"] = True
    st.session_state["subscriber_email"] = profile["email"]
    st.session_state["subscriber_profile"] = profile


def logout():
    """Clear authentication from session state."""
    st.session_state["authenticated"] = False
    st.session_state["subscriber_email"] = ""
    st.session_state["subscriber_profile"] = None


def show_login_page():
    """Render the login/register form."""

    st.markdown("""
    <style>
        .auth-container {
            max-width: 450px;
            margin: 0 auto;
            padding: 30px;
        }
        .auth-header {
            text-align: center;
            margin-bottom: 30px;
        }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("""<div class="auth-header">
        <span style="font-size: 48px;">🔶</span>
        <br><span style="color: #E67E22; font-size: 1.4rem; font-weight: 700;">Treasury Signal Intelligence</span>
        <br><span style="color: #6b7280; font-size: 0.9rem;">Sign in to access your personalized dashboard</span>
    </div>""", unsafe_allow_html=True)

    tab_login, tab_register = st.tabs(["Sign In", "Create Account"])

    with tab_login:
        login_email = st.text_input("Email", placeholder="ceo@company.com", key="login_email")
        login_password = st.text_input("Password", type="password", placeholder="Enter your password", key="login_password")

        if st.button("Sign In", type="primary", use_container_width=True):
            if login_email and login_password:
                profile = authenticate(login_email, login_password)
                if profile:
                    login_user(profile)
                    st.success(f"Welcome back, {profile['name']}!")
                    st.rerun()
                else:
                    st.error("Invalid email or password.")
            else:
                st.warning("Please enter your email and password.")

    with tab_register:
        st.markdown("**Create your account to get personalized intelligence.**")
        reg_name = st.text_input("Your Name *", placeholder="John Smith", key="reg_name")
        reg_email = st.text_input("Email *", placeholder="ceo@company.com", key="reg_email")
        reg_password = st.text_input("Password *", type="password", placeholder="Choose a password (6+ characters)", key="reg_password")
        reg_company = st.text_input("Company Name *", placeholder="Acme Corp", key="reg_company")

        r1, r2 = st.columns(2)
        with r1:
            reg_ticker = st.text_input("Ticker (optional)", placeholder="ACME", key="reg_ticker")
        with r2:
            reg_sector = st.selectbox("Sector", [
                "", "Software / Tech", "Bitcoin Mining", "Fintech / Payments",
                "Financial Services", "Asset Management", "Healthcare",
                "Energy", "E-commerce / Retail", "Automotive", "Other"
            ], key="reg_sector")

        if st.button("Create Account", type="primary", use_container_width=True):
            if reg_name and reg_email and reg_password and reg_company:
                if len(reg_password) < 6:
                    st.warning("Password must be at least 6 characters.")
                else:
                    profile = register_user(
                        name=reg_name, email=reg_email, password=reg_password,
                        company_name=reg_company, ticker=reg_ticker, sector=reg_sector,
                    )
                    if profile:
                        login_user(profile)
                        st.success(f"Account created! Welcome, {reg_name}.")
                        st.rerun()
                    else:
                        st.error("Email already registered, or an error occurred.")
            else:
                st.warning("Please fill in all required fields (*).")


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("Auth module — testing...")
    print(f"\nRun this SQL in Supabase to add the password column:")
    print(SETUP_SQL)

    # Test password hashing
    hashed = _hash_password("test123")
    assert _verify_password("test123", hashed), "Password verification failed"
    assert not _verify_password("wrong", hashed), "Wrong password should fail"
    logger.info("Password hashing: OK")
    logger.info("Auth module test complete")
