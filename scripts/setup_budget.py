#!/usr/bin/env python3
"""Create or verify the EventPulse monthly cost budget.

Usage:
    .venv/bin/python scripts/setup_budget.py --email you@example.com

Runs against the default AWS CLI profile (eventpulse-admin, AdministratorAccess).
Idempotent: if the budget already exists it prints current state and exits 0.
Email comes from --email or the BUDGET_EMAIL environment variable -- never
hardcoded, so the file is safe to commit.
"""

import argparse
import os
import sys

import boto3
from botocore.exceptions import ClientError

BUDGET_NAME = "eventpulse-monthly"
BUDGET_LIMIT_USD = 5
NOTIFICATION_THRESHOLDS = (0.8, 1.0)


def get_email() -> str:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", help="Alert recipient email (or BUDGET_EMAIL env var)")
    args = parser.parse_args()
    email = args.email or os.environ.get("BUDGET_EMAIL")
    if not email:
        sys.exit("No email given: pass --email or set BUDGET_EMAIL")
    return email


def main() -> None:
    email = get_email()
    sts = boto3.client("sts")
    budgets = boto3.client("budgets", region_name="us-east-1")
    account_id = sts.get_caller_identity()["Account"]

    notifications = [
        {
            "Notification": {
                "NotificationType": "ACTUAL",
                "ComparisonOperator": "GREATER_THAN",
                "Threshold": threshold,
                "ThresholdType": "PERCENTAGE",
                "NotificationState": "ALARM",
            },
            "Subscribers": [{"SubscriptionType": "EMAIL", "Address": email}],
        }
        for threshold in NOTIFICATION_THRESHOLDS
    ]

    def current_notifications() -> list:
        return budgets.describe_notifications_for_budget(
            AccountId=account_id, BudgetName=BUDGET_NAME
        )["Notifications"]

    try:
        existing = budgets.describe_budget(AccountId=account_id, BudgetName=BUDGET_NAME)
        budget = existing["Budget"]
        print(
            f"Budget {BUDGET_NAME} already exists: "
            f"{budget['BudgetLimit']['Amount']} {budget['BudgetLimit']['Unit']} "
            f"({budget['TimeUnit']})"
        )
        print(f"Notifications: {len(current_notifications())}")
        sys.exit(0)
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("NotFoundException", "ResourceNotFoundException"):
            sys.exit(f"describe_budget failed: {e}")

    budgets.create_budget(
        AccountId=account_id,
        Budget={
            "BudgetName": BUDGET_NAME,
            "BudgetLimit": {"Amount": str(BUDGET_LIMIT_USD), "Unit": "USD"},
            "TimeUnit": "MONTHLY",
            "BudgetType": "COST",
        },
        NotificationsWithSubscribers=notifications,
    )

    result = budgets.describe_budget(AccountId=account_id, BudgetName=BUDGET_NAME)
    print(
        f"Created budget {BUDGET_NAME}: "
        f"{result['Budget']['BudgetLimit']['Amount']} "
        f"{result['Budget']['BudgetLimit']['Unit']} / {result['Budget']['TimeUnit']}"
    )
    for notif in current_notifications():
        subs = ", ".join(s["Address"] for s in notif["Subscribers"])
        print(
            f"  threshold {notif['Notification']['Threshold']:.0%} "
            f"({notif['Notification']['ComparisonOperator']}) -> {subs}"
        )


if __name__ == "__main__":
    main()