# Agent mixed-language test samples

Sprint 8 ticket 5. A reusable fixture of realistic Arabic/French/English
samples (including code-switching and transliterated Arabic - "Arabizi" -
typical of Lebanese WhatsApp messages), run against the real agent
(`AGENT_BACKEND=openrouter`, model `deepseek/deepseek-chat`) via Django
shell. Re-run this set after any system prompt change (`integrations/agent/prompts.py`)
to catch regressions.

One sample (`pure_arabic`) is a real transcription from ticket 3's live
voice-note test, not a constructed one.

## Results (2026-08-29)

| Sample | Input | Result |
|---|---|---|
| `pure_arabic` | "مرحبا دكتور كيفك؟ بدي أحجز موعد لنهارة الثلاثة عالساعة الاربعة لو سمحت..." (real voice-note transcript: wants an appointment Tuesday at 4pm) | `ask_clarification`, reply **in Arabic**, correctly asking which service and confirming Tuesday 4pm |
| `french` | "Bonjour, je voudrais prendre un rendez-vous pour une consultation jeudi matin s'il vous plait" | `ask_clarification`, reply **in French**, correctly asking only for the missing piece (already knows "jeudi matin") |
| `english` | "Hi, can I book a consultation this Thursday morning?" | `check_availability(service="consultation")` - correct |
| `french_arabic_codeswitch` | "Bonjour, momken a3mol appointment nhar el khamis, meaning Thursday?" | `check_availability()` - correctly recognized as an availability request despite the code-switch |
| `arabizi_transliterated` | "marhaba, biddi ahjoz maw3id nhar el talata ... meaning consultation" (Arabic in Latin script) | `check_availability(service="consultation")` - correctly parsed Arabizi |
| `english_arabic_codeswitch` | "Hi habibi, 3andak appointment free bukra for a consultation?" | `check_availability(service="consultation")` - correct despite heavy code-switching |

## Findings

**No systematic tool-choice failures.** Across pure Arabic, pure French,
pure English, and three different code-switch/transliteration patterns,
the model consistently picked the right tool and extracted the right
service name. Language-matching for `ask_clarification`'s own generated
text also worked correctly (Arabic in, Arabic question back; French in,
French question back).

**Known limitation (not fixed this sprint): tool-result replies are
English-only.** `conversations/tasks.py::_format_tool_result` /
`_format_booking_result` build their reply text with hardcoded English
strings ("Here are some available times: ...", "You're booked for..."),
regardless of what language the customer wrote in - the LLM never gets a
chance to phrase them. So a French or Arabic customer would ask a
question in their language, get a correctly-reasoned tool call in
response, and then receive an **English-formatted** confirmation. This
is not fixable from the system prompt alone, since that text is plain
Python string formatting, not LLM output - it needs its own fix (most
likely: route the tool's result back through a second LLM call for
localized phrasing, rather than the current single-call-per-turn design).
Logged here as a known gap for a future sprint, per this ticket's own
"log it if not yet solvable" outcome.

## How to re-run

```sh
docker compose exec app python manage.py shell
```
```python
from tenants.models import Tenant
from conversations.models import EndUser, Conversation, Message
from integrations.agent import get_agent

tenant = Tenant.objects.get(business_name="Demo Clinic")
agent = get_agent()  # requires AGENT_BACKEND=openrouter in .env

end_user, _ = EndUser.objects.get_or_create(tenant=tenant, phone_number="+15550009999")
conversation = Conversation.objects.create(tenant=tenant, end_user=end_user)
msg = Message.objects.create(
    conversation=conversation,
    direction=Message.Direction.INBOUND,
    message_type=Message.MessageType.TEXT,
    content="<sample text here>",
)
response = agent.respond(conversation, [msg])
print(response.action, response.tool, response.tool_args, response.text)
```
