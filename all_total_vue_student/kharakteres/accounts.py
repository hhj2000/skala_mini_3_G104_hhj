"""Local account registry with salted password hashes and recovery metadata."""

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading


USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PBKDF2_ROUNDS = 310_000


class AccountStore:
    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.RLock()
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                username_key TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL,
                email_key TEXT NOT NULL UNIQUE,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")

    @staticmethod
    def password_hash(password, salt=None):
        salt = salt or secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS)
        return salt, digest.hex()

    @staticmethod
    def validate(username, email, password):
        if not USERNAME_RE.fullmatch(username):
            return "아이디는 영문·숫자와 . _ - 기호로 3~32자여야 합니다."
        if len(email) > 254 or not EMAIL_RE.fullmatch(email):
            return "이메일 주소를 확인해 주세요."
        if len(password) < 12 or len(password) > 256:
            return "비밀번호는 12~256자로 입력해 주세요."
        return None

    def count(self):
        with self.lock, sqlite3.connect(self.path) as db:
            return db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]

    def username_available(self, username):
        if not USERNAME_RE.fullmatch(username):
            return False
        with self.lock, sqlite3.connect(self.path) as db:
            return db.execute("SELECT 1 FROM accounts WHERE username_key=?", (username.casefold(),)).fetchone() is None

    def create(self, username, email, password):
        error = self.validate(username, email, password)
        if error:
            raise ValueError(error)
        salt, digest = self.password_hash(password)
        username_key, email_key = username.casefold(), email.strip().casefold()
        with self.lock, sqlite3.connect(self.path) as db:
            existed = db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] > 0
            try:
                cursor = db.execute(
                    "INSERT INTO accounts(username,username_key,email,email_key,password_salt,password_hash) VALUES (?,?,?,?,?,?)",
                    (username, username_key, email.strip(), email_key, salt, digest),
                )
            except sqlite3.IntegrityError as exc:
                if db.execute("SELECT 1 FROM accounts WHERE username_key=?", (username_key,)).fetchone():
                    raise ValueError("이미 사용 중인 아이디입니다.") from exc
                raise ValueError("이미 가입된 이메일입니다.") from exc
            return {"id": cursor.lastrowid, "username": username}, not existed

    def authenticate(self, username, password):
        with self.lock, sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT id,username,password_salt,password_hash FROM accounts WHERE username_key=?",
                (username.casefold(),),
            ).fetchone()
        if not row:
            # Keep the work factor comparable for unknown IDs.
            self.password_hash(password, "00112233445566778899aabbccddeeff")
            return None
        _, digest = self.password_hash(password, row[2])
        if not hmac.compare_digest(digest, row[3]):
            return None
        return {"id": row[0], "username": row[1]}

    def find_username(self, email):
        with self.lock, sqlite3.connect(self.path) as db:
            row = db.execute("SELECT username FROM accounts WHERE email_key=?", (email.strip().casefold(),)).fetchone()
        return row[0] if row else None

    def reset_password(self, username, email, password):
        if len(password) < 12 or len(password) > 256:
            raise ValueError("새 비밀번호는 12~256자로 입력해 주세요.")
        salt, digest = self.password_hash(password)
        with self.lock, sqlite3.connect(self.path) as db:
            cursor = db.execute(
                "UPDATE accounts SET password_salt=?,password_hash=? WHERE username_key=? AND email_key=?",
                (salt, digest, username.casefold(), email.strip().casefold()),
            )
            return cursor.rowcount == 1
