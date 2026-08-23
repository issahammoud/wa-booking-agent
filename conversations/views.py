from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView

from conversations.models import Conversation
from core.mixins import TenantScopedMixin


class ConversationListView(LoginRequiredMixin, TenantScopedMixin, ListView):
    """Placeholder staff dashboard landing page.

    Proves TenantScopedMixin works end-to-end; Sprint 7 replaces this
    with the real dashboard.
    """

    model = Conversation
