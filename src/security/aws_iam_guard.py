from datetime import datetime


ALLOWED_IAM_ACTIONS = [

    "bedrock:InvokeModel",
    "s3:GetObject",
    "s3:PutObject",
    "logs:CreateLogStream",
    "logs:PutLogEvents"
]


BLOCKED_IAM_ACTIONS = [

    "iam:DeleteUser",
    "iam:DeleteRole",
    "kms:DeleteKey",
    "organizations:LeaveOrganization",
    "ec2:TerminateInstances"
]


def validate_iam_action(

    action
):

    # BLOCKED ACTIONS
    if action in BLOCKED_IAM_ACTIONS:

        return {

            "allowed": False,

            "severity": "CRITICAL",

            "timestamp": str(datetime.utcnow()),

            "message": "Dangerous IAM action blocked"
        }

    # UNKNOWN ACTIONS
    if action not in ALLOWED_IAM_ACTIONS:

        return {

            "allowed": False,

            "severity": "HIGH",

            "timestamp": str(datetime.utcnow()),

            "message": "Unauthorized IAM action"
        }

    return {

        "allowed": True,

        "severity": "SAFE",

        "timestamp": str(datetime.utcnow()),

        "message": "IAM action approved"
    }


# TEST
if __name__ == "__main__":

    result = validate_iam_action(
        "bedrock:InvokeModel"
    )

    print(result)