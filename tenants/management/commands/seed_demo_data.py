from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from bookings.models import Service
from tenants.models import Tenant

DEMO_PASSWORD = "demo-pass-1234"


class Command(BaseCommand):
    help = "Create a demo tenant, platform admin, and owner staff user for local testing/demos."

    def handle(self, *args, **options):
        User = get_user_model()

        platform_admin, created = User.objects.get_or_create(
            username="platform_admin",
            defaults={"role": User.Role.PLATFORM_ADMIN, "is_staff": True, "is_superuser": True},
        )
        if created:
            platform_admin.set_password(DEMO_PASSWORD)
            platform_admin.save()
            self.stdout.write(self.style.SUCCESS("Created platform_admin"))
        else:
            self.stdout.write("platform_admin already exists, skipping")

        tenant, created = Tenant.objects.get_or_create(
            business_name="Demo Clinic",
            defaults={
                "vertical": Tenant.Vertical.DOCTOR,
                "working_hours": {
                    "mon": ["09:00", "17:00"],
                    "tue": ["09:00", "17:00"],
                    "wed": ["09:00", "17:00"],
                    "thu": ["09:00", "17:00"],
                    "fri": ["09:00", "17:00"],
                },
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS("Created Demo Clinic tenant"))
        else:
            self.stdout.write("Demo Clinic tenant already exists, skipping")

        owner, created = User.objects.get_or_create(
            username="demo_owner",
            defaults={"tenant": tenant, "role": User.Role.OWNER, "is_staff": True},
        )
        if created:
            owner.set_password(DEMO_PASSWORD)
            owner.save()
            self.stdout.write(self.style.SUCCESS("Created demo_owner"))
        else:
            self.stdout.write("demo_owner already exists, skipping")

        for name, duration in [("Consultation", 30), ("Follow-up", 15)]:
            _, created = Service.objects.get_or_create(
                tenant=tenant, name=name, defaults={"duration_minutes": duration}
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created service '{name}'"))
            else:
                self.stdout.write(f"Service '{name}' already exists, skipping")

        self.stdout.write(
            self.style.WARNING(
                f"Demo login credentials (local/dev only): "
                f"platform_admin / demo_owner, password '{DEMO_PASSWORD}'"
            )
        )
