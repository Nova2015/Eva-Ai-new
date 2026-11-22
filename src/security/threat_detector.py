from datetime import datetime

THREAT_LEVELS = {
    0: "SAFE",
    1: "LOW",
    5: "MEDIUM",
    10: "HIGH",
    20: "CRITICAL"
}


def calculate_threat_score(

    prompt_result,
    rag_result,
    output_result
):

    total_score = 0

    # Prompt Security
    if prompt_result:

        total_score += prompt_result.get(
            "threat_score",
            0
        )

    # RAG Security
    if rag_result:

        total_score += rag_result.get(
            "risk_score",
            0
        )

    # Output Security
    if output_result:

        total_score += output_result.get(
            "risk_score",
            0
        )

    # Final Threat Level
    if total_score >= 30:

        level = "CRITICAL"

    elif total_score >= 15:

        level = "HIGH"

    elif total_score >= 5:

        level = "MEDIUM"

    elif total_score >= 1:

        level = "LOW"

    else:

        level = "SAFE"

    return {

        "timestamp": str(datetime.utcnow()),

        "threat_score": total_score,

        "threat_level": level,

        "blocked": level in [
            "HIGH",
            "CRITICAL"
        ]
    }


if __name__ == "__main__":

    prompt_security = {
        "threat_score": 10
    }

    rag_security = {
        "risk_score": 5
    }

    output_security = {
        "risk_score": 20
    }

    result = calculate_threat_score(

        prompt_security,
        rag_security,
        output_security
    )

    print(result)