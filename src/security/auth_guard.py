from jose import jwt, JWTError
from datetime import datetime, timedelta
from passlib.context import CryptContext

# SECRET KEY
SECRET_KEY = "SUPER_SECRET_AI_KEY"

# JWT Algorithm
ALGORITHM = "HS256"

# Token Expire Time
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Password Hashing
pwd_context = CryptContext(

    schemes=["bcrypt"],

    deprecated="auto"
)


# ─────────────────────────────────────────
# HASH PASSWORD
# ─────────────────────────────────────────

def hash_password(password):

    return pwd_context.hash(password)


# ─────────────────────────────────────────
# VERIFY PASSWORD
# ─────────────────────────────────────────

def verify_password(

    plain_password,
    hashed_password
):

    return pwd_context.verify(

        plain_password,
        hashed_password
    )


# ─────────────────────────────────────────
# CREATE JWT TOKEN
# ─────────────────────────────────────────

def create_access_token(

    data: dict,

    expires_delta=None
):

    to_encode = data.copy()

    expire = datetime.utcnow() + (

        expires_delta or
        timedelta(
            minutes=ACCESS_TOKEN_EXPIRE_MINUTES
        )
    )

    to_encode.update({

        "exp": expire
    })

    encoded_jwt = jwt.encode(

        to_encode,

        SECRET_KEY,

        algorithm=ALGORITHM
    )

    return encoded_jwt


# ─────────────────────────────────────────
# VERIFY JWT TOKEN
# ─────────────────────────────────────────

def verify_token(token):

    try:

        payload = jwt.decode(

            token,

            SECRET_KEY,

            algorithms=[ALGORITHM]
        )

        return {

            "valid": True,

            "payload": payload
        }

    except JWTError:

        return {

            "valid": False,

            "message": "Invalid token"
        }


# ─────────────────────────────────────────
# TEST
# ─────────────────────────────────────────

if __name__ == "__main__":

    # HASH
    hashed = hash_password(
        "admin123"
    )

    print("HASHED:", hashed)

    # VERIFY PASSWORD
    verified = verify_password(

        "admin123",

        hashed
    )

    print("PASSWORD VERIFIED:", verified)

    # CREATE TOKEN
    token = create_access_token({

        "sub": "admin",

        "role": "super_admin"
    })

    print("TOKEN:", token)

    # VERIFY TOKEN
    decoded = verify_token(token)

    print("DECODED:", decoded)