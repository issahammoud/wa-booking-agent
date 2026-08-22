import pytest
from django.contrib.auth import get_user_model

from tenants.models import Tenant

User = get_user_model()


@pytest.fixture
def tenant(db):
    return Tenant.objects.create(business_name="Test Tenant", vertical=Tenant.Vertical.DOCTOR)


@pytest.fixture
def other_tenant(db):
    return Tenant.objects.create(business_name="Other Tenant", vertical=Tenant.Vertical.LAWYER)


@pytest.fixture
def staff_user(tenant):
    return User.objects.create_user(
        username="staff", password="pass-12345", tenant=tenant, role=User.Role.STAFF
    )


@pytest.fixture
def platform_admin_user(db):
    return User.objects.create_user(
        username="platform_admin", password="pass-12345", role=User.Role.PLATFORM_ADMIN
    )
