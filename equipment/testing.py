"""Helpers for tests that need loans."""

from .models import Loan, LoanLine


def make_usage(*, equipment, quantity, **loan_fields):
    """Create a one-line loan and return its line (the thing lists show)."""
    loan = Loan.objects.create(**loan_fields)
    return LoanLine.objects.create(loan=loan, equipment=equipment, quantity=quantity)
