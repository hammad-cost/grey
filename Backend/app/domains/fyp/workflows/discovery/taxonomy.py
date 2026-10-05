"""
Industry and branch taxonomy.

This is static, deterministic data — no AI needed to produce it.
The student picks from these lists using UI cards.

To add a new industry or branch: edit this file only.
Nothing else in the codebase needs to change.
"""

# Ordered list of selectable industries.
# Shown to the student as clickable cards.
INDUSTRIES: list[str] = [
    "Healthcare",
    "Defense",
    "Finance",
    "Agriculture",
    "Education",
    "Cybersecurity",
    "Transportation",
    "Manufacturing",
    "Energy",
    "Logistics",
    "Retail",
    "Smart Cities",
    "Environment",
    "Telecommunications",
    "Government Services",
]

# Branches for each industry.
# Shown after the student picks an industry.
_BRANCHES: dict[str, list[str]] = {
    "Healthcare": [
        "Clinical AI",
        "Medical Imaging",
        "Drug Discovery",
        "Hospital Operations",
        "Mental Health",
        "Public Health",
    ],
    "Defense": [
        "Army",
        "Navy",
        "Air Force",
        "Cyber Defense",
        "Defense Logistics",
        "Intelligence",
        "Disaster / Emergency Operations",
    ],
    "Finance": [
        "Banking",
        "Insurance",
        "Investment",
        "Fraud Detection",
        "RegTech",
        "Islamic Finance",
    ],
    "Agriculture": [
        "Precision Farming",
        "Crop Disease Detection",
        "Supply Chain",
        "Livestock Management",
        "Irrigation Management",
    ],
    "Education": [
        "E-Learning",
        "Student Analytics",
        "Adaptive Learning",
        "Special Needs Support",
        "Assessment & Grading",
    ],
    "Cybersecurity": [
        "Network Security",
        "Threat Intelligence",
        "Identity & Access Management",
        "Malware Analysis",
        "Compliance & Audit",
    ],
    "Transportation": [
        "Traffic Management",
        "Autonomous Vehicles",
        "Public Transit",
        "Aviation",
        "Maritime",
        "Ride-Sharing & Mobility",
    ],
    "Manufacturing": [
        "Quality Control",
        "Predictive Maintenance",
        "Supply Chain",
        "Process Automation",
        "Workplace Safety",
    ],
    "Energy": [
        "Renewable Energy",
        "Smart Grid",
        "Oil & Gas",
        "Energy Efficiency",
        "Demand Forecasting",
    ],
    "Logistics": [
        "Supply Chain Optimization",
        "Last-Mile Delivery",
        "Warehouse Management",
        "Fleet Management",
        "Cold Chain",
    ],
    "Retail": [
        "Customer Analytics",
        "Inventory Management",
        "Demand Forecasting",
        "Fraud Prevention",
        "Dynamic Pricing",
    ],
    "Smart Cities": [
        "Traffic & Mobility",
        "Waste Management",
        "Public Safety",
        "Energy Management",
        "Urban Planning",
    ],
    "Environment": [
        "Climate Monitoring",
        "Disaster Prediction",
        "Air Quality",
        "Biodiversity",
        "Water Management",
    ],
    "Telecommunications": [
        "Network Optimization",
        "Customer Churn Prediction",
        "Fraud Detection",
        "5G Planning",
        "IoT Management",
    ],
    "Government Services": [
        "Public Safety",
        "Social Services",
        "Tax Administration",
        "Digital Identity",
        "Smart Administration",
    ],
}


def get_branches_for_industry(industry: str) -> list[str]:
    """
    Return the list of branches for a given industry.
    Returns an empty list if the industry is not recognised.
    """
    return _BRANCHES.get(industry, [])


def is_valid_industry(industry: str) -> bool:
    return industry in INDUSTRIES


def is_valid_branch(industry: str, branch: str) -> bool:
    return branch in get_branches_for_industry(industry)
