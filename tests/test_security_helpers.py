from models.security import is_strong_password, is_valid_email, is_valid_role

def test_password_policy_accepts_strong_password():
    assert is_strong_password("StrongPass1!") is True

def test_password_policy_rejects_weak_password():
    assert is_strong_password("password") is False
    assert is_strong_password("Short1!") is False
    assert is_strong_password("NoSpecialChar123") is False

def test_role_validation():
    assert is_valid_role("admin") is True
    assert is_valid_role("custodian") is True
    assert is_valid_role("technician") is True
    assert is_valid_role("faculty") is True
    assert is_valid_role("invalid_role") is False

def test_email_validation():
    assert is_valid_email("user@school.edu") is True
    assert is_valid_email("invalid-email") is False
