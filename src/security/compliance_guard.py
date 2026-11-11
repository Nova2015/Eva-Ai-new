from datetime import datetime


class ComplianceGuard:

    def __init__(self):

        self.blocked_terms = [

            "patient medical record",
            "credit card number",
            "aadhaar number",
            "private password",
            "secret token"
        ]

    def check_compliance(

        self,
        text
    ):

        detected = []

        lower_text = text.lower()

        for term in self.blocked_terms:

            if term in lower_text:

                detected.append(term)

        if detected:

            return {

                "compliant": False,

                "severity": "HIGH",

                "detected": detected,

                "timestamp": str(datetime.utcnow()),

                "message": "Compliance violation detected"
            }

        return {

            "compliant": True,

            "severity": "SAFE",

            "timestamp": str(datetime.utcnow()),

            "message": "Compliance passed"
        }


if __name__ == "__main__":

    guard = ComplianceGuard()

    result = guard.check_compliance(
        "This contains private password"
    )

    print(result)