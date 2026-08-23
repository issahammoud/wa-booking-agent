# WhatsApp Cloud API setup

How to stand up a test WhatsApp Business Account (WABA) and wire it to
this app's webhook. This describes the *process* only - no secret
values belong in this file or in git at all.

## 1. Create a Meta App and test WABA

1. Go to [developers.facebook.com](https://developers.facebook.com/)
   and create a new App (type: Business).
2. Add the **WhatsApp** product to the App.
3. Under WhatsApp > API Setup, Meta provisions a **test WhatsApp
   Business Account** and a **test phone number** for free - no real
   phone number or Meta Business verification needed for development.
4. From that same page, note down (into your own password manager or
   local `.env` - never into this repo or chat):
   - **App ID** and **App Secret** (App Dashboard > Settings > Basic)
   - **WABA ID** and **Phone number ID** (WhatsApp > API Setup)
   - A **temporary access token** (also API Setup - expires in 24h;
     good enough to prove the setup works, not for anything long-lived)
5. Sanity check before writing any of our own code: send a test
   message from the API Setup page's built-in "Send message" tool to
   your own WhatsApp number, and confirm it arrives. This proves the
   WABA itself works, independent of this app.

## 2. Expose your local server

Meta needs a public HTTPS URL to reach your webhook. For local
development, tunnel your machine with something like
[ngrok](https://ngrok.com/):

```sh
ngrok http 8000
```

Use the `https://...ngrok-free.app` URL it prints as the webhook base
URL in the next step. (In a deployed environment, use the real
public URL instead - no tunnel needed.)

## 3. Configure the webhook

1. In the Meta App dashboard, go to WhatsApp > Configuration (or the
   App's Webhooks product).
2. Set the **Callback URL** to `<your-public-url>/webhook/whatsapp/`.
3. Choose any **Verify token** string yourself - it isn't provided by
   Meta, you invent it. Put the same value in this project's `.env` as
   `WHATSAPP_WEBHOOK_VERIFY_TOKEN`.
4. Click **Verify and Save**. Meta immediately sends a `GET` request
   to your callback URL to confirm you control it - this only succeeds
   once the app is running and reachable at that URL (see
   `integrations/views.py::whatsapp_webhook` for the handshake logic).
5. Subscribe to the **messages** webhook field.

## 4. Map credentials to this project

| Meta credential                  | Where it goes                                                        |
| --------------------------------- | --------------------------------------------------------------------- |
| App Secret                        | `.env` → `WHATSAPP_APP_SECRET` (verifies inbound webhook signatures)  |
| Verify token (your own choice)    | `.env` → `WHATSAPP_WEBHOOK_VERIFY_TOKEN`                              |
| WABA ID                           | `Tenant.waba_id` (per tenant, via `/admin/` or a seed/onboarding flow) |
| Phone number ID                   | `Tenant.phone_number_id` (per tenant - this is how an inbound webhook is routed to the right tenant) |
| Access token                      | `Tenant.whatsapp_access_token` (per tenant, encrypted storage - used for sending, not receiving) |

The App Secret and verify token are platform-level: one Meta App and
one webhook subscription serve every tenant, each identified inside
the payload by its own `phone_number_id`.

## 5. Restart and re-verify

After editing `.env`, restart the app (`make down && make up`) so the
new environment variables are picked up, then repeat step 3's "Verify
and Save" if it hadn't succeeded yet.
