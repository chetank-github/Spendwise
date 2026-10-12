import enum


class UserRole(str, enum.Enum):
    employee = "employee"
    manager = "manager"
    finance = "finance"


class ExpenseStatus(str, enum.Enum):
    draft = "draft"
    submitted = "submitted"
    approved = "approved"
    rejected = "rejected"
    reimbursed = "reimbursed"


class ExpenseCategory(str, enum.Enum):
    travel = "travel"
    meals = "meals"
    accommodation = "accommodation"
    office_supplies = "office_supplies"
    software = "software"
    training = "training"
    client_entertainment = "client_entertainment"
    other = "other"