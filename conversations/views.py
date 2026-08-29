from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import DetailView, ListView

from conversations.models import Conversation
from core.mixins import TenantScopedMixin


class ConversationListView(LoginRequiredMixin, TenantScopedMixin, ListView):
    """Staff dashboard view of every conversation for the logged-in user's tenant."""

    model = Conversation

    def get_queryset(self):
        return super().get_queryset().order_by("-last_message_at")


class ConversationDetailView(LoginRequiredMixin, TenantScopedMixin, DetailView):
    """Read-only view of a single conversation's full message history."""

    model = Conversation
