from datetime import datetime
from jose import jwt


SECRET_KEY = "SUPER_AI_SECURITY_KEY"

ALGORITHM = "HS256"


class JWTGuard:

    # CREATE TOKEN
    def generate_token(

        self,
        user_id,
        role="user"
    ):

        payload = {

            "user_id": user_id,

            "role": role,

            "created_at": str(datetime.utcnow())
        }

        token = jwt.encode(

            payload,

            SECRET_KEY,

            algorithm=ALGORITHM
        )

        return token

    # VERIFY TOKEN
    def verify_token(

        self,
        token
    ):

        try:

            decoded = jwt.decode(

                token,

                SECRET_KEY,

                algorithms=[ALGORITHM]
            )

            return {

                "valid": True,

                "data": decoded
            }

        except Exception as error:

            return {

                "valid": False,

                "message": str(error)
            }


# TEST
if __name__ == "__main__":

    auth = JWTGuard()

    token = auth.generate_token(

        "admin",

        "super_admin"
    )

    print(token)

    result = auth.verify_token(
        token
    )

    print(result)
