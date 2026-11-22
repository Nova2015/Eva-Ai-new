from datetime import datetime


class ThreatIntelligence:

    def __init__(self):

        self.known_attack_patterns = [

            "prompt injection",
            "jailbreak",
            "token theft",
            "credential leak",
            "sql injection",
            "xss attack",
            "remote code execution"
        ]

        self.threat_feed = []

    # ANALYZE THREAT
    def analyze_threat(

        self,
        text
    ):

        detected = []

        lower_text = text.lower()

        for pattern in self.known_attack_patterns:

            if pattern in lower_text:

                detected.append(pattern)

        if detected:

            threat = {

                "detected": detected,

                "severity": "CRITICAL",

                "timestamp": str(datetime.utcnow()),

                "message": "Threat intelligence match found"
            }

            self.threat_feed.append(threat)

            return {

                "safe": False,

                "threat": threat
            }

        return {

            "safe": True,

            "message": "No known threats detected"
        }

    # GET FEED
    def get_threat_feed(self):

        return self.threat_feed


if __name__ == "__main__":

    intel = ThreatIntelligence()

    result = intel.analyze_threat(
        "This is a prompt injection attack"
    )

    print(result)

    print(intel.get_threat_feed())