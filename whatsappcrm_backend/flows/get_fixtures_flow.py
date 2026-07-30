# whatsappcrm_backend/flows/get_fixtures_flow.py

def create_get_fixtures_flow():
    """
    Retired: fixture browsing is now handled interactively by the Betting Flow
    (see betting_flow.py). This flow is kept only so any lingering active session
    or stray trigger is redirected into the new tap-driven browser rather than
    the old PDF experience. It is loaded as inactive and carries no trigger
    keywords, so it never starts on its own — the "fixtures"/"matches" keywords
    now belong to the Betting Flow.
    """
    return {
        "name": "View Football Fixtures",
        "description": "Retired PDF fixtures flow — redirects into the interactive Betting Flow.",
        "trigger_keywords": [],
        "is_active": False,
        "requires_login": True,
        "steps": [
            {
                "name": "redirect_to_betting",
                "step_type": "action",
                "is_entry_point": True,
                "config": {
                    "actions_to_run": [
                        {"action_type": "switch_flow", "trigger_keyword_template": "bet"}
                    ]
                },
                "transitions": [],
            }
        ],
    }
