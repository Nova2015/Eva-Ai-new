from billing.billing_store import list_invoices


def phase_invoices(organization_id: str):
    return list_invoices(organization_id)
