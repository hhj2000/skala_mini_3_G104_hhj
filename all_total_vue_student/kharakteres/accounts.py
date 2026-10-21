"""Account registry, password/recovery metadata and durable single-login grants.

Token hashes and a UNIQUE user index enforce latest-login-wins across managers
sharing this database. Local signing keys persist here when not supplied in env."""

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading


USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PBKDF2_ROUNDS = 310_000


class SessionReplaced(Exception):
    """A session rotation lost to a newer login; never restore the old grant."""


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
            # Only token hashes and the secret-mode flag persist, never browser tokens or secret content.
            db.execute("CREATE TABLE IF NOT EXISTS auth_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS login_sessions (
                token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL,
                secret_mode INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")

            # Migrate old multi-login registries atomically, retaining the latest login per account.
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM login_sessions WHERE rowid NOT IN (SELECT MAX(rowid) FROM login_sessions GROUP BY user_id)")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_login_per_account ON login_sessions(user_id)")

    def session_key(self):
        """Persist the local signing key so login survives process/container restart."""
        with self.lock, sqlite3.connect(self.path) as db:
            db.execute("INSERT OR IGNORE INTO auth_metadata(key,value) VALUES ('session_key',?)", (secrets.token_hex(32),))
            return bytes.fromhex(db.execute("SELECT value FROM auth_metadata WHERE key='session_key'").fetchone()[0])

    @staticmethod
    def session_hash(sid):
        return hashlib.sha256(sid.encode()).hexdigest()

    def save_session(self, sid, user_id, previous_sid=None):
        """Latest successful login wins, even across managers sharing this SQLite DB.

        Rotation (secret-mode exit) must still own the previous grant. Login itself
        intentionally replaces any existing grant. The delete/insert is one transaction.
        """
        with self.lock, sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            previous=db.execute("SELECT token_hash FROM login_sessions WHERE user_id=?",(user_id,)).fetchall()
            hashes={row[0] for row in previous}
            if previous_sid is not None and self.session_hash(previous_sid) not in hashes:
                raise SessionReplaced()
            db.execute("DELETE FROM login_sessions WHERE user_id=?",(user_id,))
            db.execute("INSERT INTO login_sessions(token_hash,user_id) VALUES (?,?)", (self.session_hash(sid),user_id))
        return hashes

    def load_session(self, sid):
        with self.lock, sqlite3.connect(self.path) as db:
            row=db.execute("SELECT a.id,a.username,s.secret_mode FROM login_sessions s JOIN accounts a ON a.id=s.user_id WHERE s.token_hash=?",(self.session_hash(sid),)).fetchone()
        return {"id":row[0],"username":row[1],"secret_mode":bool(row[2])} if row else None

    def set_session_secret(self, sid, enabled):
        with self.lock, sqlite3.connect(self.path) as db:
            return db.execute("UPDATE login_sessions SET secret_mode=? WHERE token_hash=?",(int(enabled),self.session_hash(sid))).rowcount==1

    def revoke_session(self, sid):
        with self.lock, sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM login_sessions WHERE token_hash=?",(self.session_hash(sid),))

    def revoke_user_sessions(self, username):
        with self.lock, sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM login_sessions WHERE user_id IN (SELECT id FROM accounts WHERE username_key=?)",(username.casefold(),))

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
