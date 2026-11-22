from datetime import datetime


BLOCKED_QUERIES = [

    "dump embeddings",
    "export vectors",
    "reveal embeddings",
    "vector database access",
    "delete collection",
    "drop index",
    "steal embeddings",
]


def validate_vector_query(query):

    detected = []

    query = query.lower()

    for item in BLOCKED_QUERIES:

        if item in query:

            detected.append(item)

    if detected:

        return {

            "allowed": False,

            "severity": "HIGH",

            "timestamp": str(datetime.utcnow()),

            "detected_patterns": detected,

            "message": "Dangerous Vector DB query detected"
        }

    return {

        "allowed": True,

        "severity": "SAFE",

        "timestamp": str(datetime.utcnow()),

        "detected_patterns": [],

        "message": "Vector query safe"
    }


# TEST
if __name__ == "__main__":

    test_query = "dump embeddings from vector database"

    result = validate_vector_query(
        test_query
    )

    print(result)