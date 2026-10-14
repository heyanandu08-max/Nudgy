<!-- Draft: have a lawyer review before launch. Served at /privacy; {{placeholders}} come from the server settings. -->
# Privacy Policy

Last updated: {{updated}}

Nudgy is a desktop tutor made by **{{company}}** ({{address}}). To answer a question about
what's on your screen it has to look at your screen, so this page says exactly when it looks,
what it sends, to whom, and for how long. Questions or requests: [{{email}}](mailto:{{email}}).

## When Nudgy looks at your screen

- **Only when you ask**: while you hold the hotkey, or after you open the question box with a double tap.
- **During a lesson you started**: each time you pause, to check whether you did the step.
- **When you press "Explain an error"**: once, like a question.
- **While you record a walkthrough**: a small picture per click, kept on your computer.

Nudgy does not watch your screen in the background. Every time it captures, a "looking at your
screen" tag appears on that screen. It never captures while a password field has focus, or
when an app on your "Never look at these apps" list is in front (password managers are on it
by default).

**Shortcut tips (off unless you turn them on).** When on, Nudgy notices your clicks and reads
only the name of the button you clicked (for example "Bold") to tell you its keyboard
shortcut. No screenshot is taken and nothing is sent anywhere.

## What is sent, and to whom

For each question or lesson check, the app sends to the Nudgy server ({{site}}):

| Data | Why |
| --- | --- |
| One screenshot of the monitor your cursor is on (downscaled) | so the answer matches your screen |
| Names, roles and positions of buttons in the app in front | so Nudgy can point at the right one |
| The app name and window title | context |
| Your spoken question (audio) or typed text | the question |
| Your language, voice, answer length and beginner-mode settings | how to answer |

The server passes the screenshot, button list and question to the AI services below, which
turn speech into text, write the answer and speak it. Each processes it for that request under
its own API terms, which you can read on its website.

**Not stored.** Screenshots and audio are processed in memory for that one request and then
discarded. They are never written to disk or logs, on your computer or on the server. Server
logs hold metadata only (request type, sizes, timings, error codes).

## Services we use

| Service | What it receives | Why |
| --- | --- | --- |
| Anthropic (Claude) | Screenshot, button list, your question | Writes the answer and lesson steps |
| Deepgram or OpenAI (Whisper) | Your spoken question | Speech to text |
| ElevenLabs or OpenAI (text to speech) | The answer text | Nudgy's voice |
| PayPal | Your subscription and payment | Payments (we never see card or bank details) |
| Google or Apple | Only if you sign in with them: your email | Sign-in |
| Our email provider | Your email address | Sign-in links and team invitations |
| GitHub | Your IP address when the app checks for updates | App updates |

Which speech services are used depends on the server's setup. There are no advertising,
analytics or crash-reporting tools in the app.

## What is stored

**On your computer** (in the app's data folder): lessons, skills and review schedule, your
streak, the text of your recent questions (last 200), recorded walkthroughs, and your
settings. Nothing here is uploaded unless you share it.

**On the server, only if you create an account:**

- Your email address (no name or profile: we don't need them)
- When you agreed to these terms and confirmed you are 13 or older
- Your plan and subscription status
- A count of questions and lessons, with sizes and timings, for plan limits
- Your team membership, and walkthroughs and courses you chose to share
- On a team: whether you finished your team's walkthroughs, steps passed, hints used and the
  step that needed the most help, so your team owner can see them (never anything from your screen)

Shared links are unlisted, but anyone with a link can open it. Shared copies leave out
screenshots unless you choose to include them. We keep account data until you delete your
account.

## Your choices and rights

- **See and export**: Settings → Privacy → Export my data saves one file with everything above.
- **Delete**: Settings → Privacy → "Delete learning history" wipes this computer; "Delete my
  account" deletes your account, usage records, shared links and (for team owners) the team,
  and cancels any subscription. See [Delete your account](/delete-account), also for requests
  without the app.
- **Pause**: the tray menu's Pause turns the hotkey off entirely.
- **Blocklist**: Settings → Cursor & voice → "Never look at these apps".
- **Emails**: we only send sign-in links you ask for and team invitations; every invitation has
  an unsubscribe link.

Depending on where you live (for example the EU, UK, India or California) you may also have
the right to correct your data, object to or restrict its use, and complain to a data
protection authority. Write to [{{email}}](mailto:{{email}}) and we will answer within 30 days.

## Children

Nudgy is for people aged 13 and older (or the minimum age for consent in your country, for
example 16 in some EU countries). Signing in asks you to confirm your age. We do not knowingly
collect data from younger children; if you believe a child has an account, write to us and
we will delete it.

## Cookies

The app uses no cookies. Our web pages use none either unless you accept optional analytics;
see the [Cookie Policy](/cookies).

## Changes

If this policy changes in a way that matters, the app asks you to agree again the next time
you sign in. The date at the top shows the current version.

## Contact

{{company}}, {{address}}, {{country}}. Email: [{{email}}](mailto:{{email}}).
