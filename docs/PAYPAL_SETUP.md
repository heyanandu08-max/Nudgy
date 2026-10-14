# Setting up PayPal payments

About 20 minutes. Do it all in **sandbox** (fake money) first, test a purchase, then repeat
steps 2–5 in **live**.

## 1. Accounts

1. Create a free **PayPal Business** account at paypal.com (or upgrade a personal one).
2. Log in at **developer.paypal.com** with it.

## 2. App credentials

1. developer.paypal.com → **Apps & Credentials** → make sure the toggle says **Sandbox**.
2. **Create App** → name it `Nudgy` → type **Merchant** → Create.
3. Copy the **Client ID** and the **Secret**.
4. Put them in the `.env` file next to the server (never in chat, email or git):

```
PAYPAL_ENV=sandbox
PAYPAL_CLIENT_ID=<Client ID>
PAYPAL_CLIENT_SECRET=<Secret>
```

## 3. Product and plans (automatic)

```
cd backend
python -m app.paypal_setup --team-price <USD per seat per month>
```

It creates the "Nudgy Pro" product, Pro monthly ($20), Pro yearly ($40) and, if you give a
price, the Team plan, then prints lines like:

```
PAYPAL_PLAN_PRO=P-...
PAYPAL_PLAN_PRO_YEARLY=P-...
PAYPAL_PLAN_TEAM=P-...
```

Copy them into `.env`. Running it again is safe: it reuses what exists. Leave out
`--team-price` until you've chosen one.

## 4. Webhook (once the server has a public https address)

```
python -m app.paypal_setup --webhook-url https://<your server>/v1/billing/webhook
```

Copy the printed `PAYPAL_WEBHOOK_ID=...` into `.env`. This is how renewals, cancellations
and failed payments reach Nudgy. Without it, subscribing still works (the return page
confirms it), but later changes won't sync.

## 5. Restart and test with fake money

1. Restart the server.
2. developer.paypal.com → **Testing tools → Sandbox accounts**: use the **Personal** test
   account's email and password (click it to see them) as the buyer.
3. In Nudgy: sign in → Settings → Plan → Subscribe monthly → log in to PayPal with the
   test buyer → Agree & Subscribe.
4. Back in Nudgy, Settings → Plan should say **Pro (current plan)**.
5. Settings → Account → **Manage in PayPal** → cancel: Nudgy keeps Pro until the paid period
   ends.

## 6. Go live

Switch the developer dashboard toggle to **Live**, create the app again, and repeat steps
2–4 with `PAYPAL_ENV=live` and the live Client ID and Secret. Live and sandbox have different
plan IDs and webhook IDs; replace all of them in `.env`.

The server refuses to start in production with `PAYPAL_ENV=sandbox`, so you can't forget.
