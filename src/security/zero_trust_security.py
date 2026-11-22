from datetime import datetime


class ZeroTrustSecurity:

    def __init__(self):

        self.allowed_users = {

            "admin": "super_admin",

            "analyst": "security_team",

            "user": "basic_user"
        }

        self.failed_attempts = {}

    # VERIFY USER
    def verify_identity(

        self,
        username,
        role
    ):

        if username not in self.allowed_users:

            return {

                "allowed": False,

                "message": "Unknown user"
            }

        if self.allowed_users[username] != role:

            self.track_failure(username)

            return {

                "allowed": False,

                "message": "Role mismatch"
            }

        return {

            "allowed": True,

            "message": "Identity verified"
        }

    # DEVICE TRUST
    def verify_device(

        self,
        device_id
    ):

        trusted_devices = [

            "AI_SERVER_001",

            "AWS_NODE_01",

            "BEDROCK_GATEWAY"
        ]

        if device_id not in trusted_devices:

            return {

                "allowed": False,

                "message": "Untrusted device"
            }

        return {

            "allowed": True
        }

    # LOCATION TRUST
    def verify_location(

        self,
        country
    ):

        blocked_locations = [

            "Unknown",

            "Tor",

            "DarkWeb"
        ]

        if country in blocked_locations:

            return {

                "allowed": False,

                "message": "Blocked location"
            }

        return {

            "allowed": True
        }

    # FAILURE TRACKING
    def track_failure(

        self,
        username
    ):

        if username not in self.failed_attempts:

            self.failed_attempts[username] = 1

        else:

            self.failed_attempts[username] += 1

    # GET FAILURES
    def get_failures(self):

        return self.failed_attempts


# TEST
if __name__ == "__main__":

    zero_trust = ZeroTrustSecurity()

    result = zero_trust.verify_identity(

        "admin",

        "super_admin"
    )

    print(result)

    device = zero_trust.verify_device(
        "AI_SERVER_001"
    )

    print(device)

    location = zero_trust.verify_location(
        "India"
    )

    print(location)