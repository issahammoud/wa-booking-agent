class TenantScopedMixin:
    """Restrict a view's queryset to request.user's tenant.

    Platform admins (role=platform_admin) are exempt and see all tenants'
    data. Requires the view's model to have a `tenant` FK, and must be
    combined with LoginRequiredMixin (assumes an authenticated StaffUser).
    """

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if user.role == user.Role.PLATFORM_ADMIN:
            return queryset
        return queryset.filter(tenant=user.tenant)
