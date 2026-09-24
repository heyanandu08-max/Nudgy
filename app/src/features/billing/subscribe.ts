export type SubscribeResult = { ok: true } | { ok: false; reason: "not_connected" };

/**
 * The one entry point for "Subscribe" (upgrade screen and Account).
 * TODO: connect billing provider. The backend already has Stripe Checkout
 * (`invoke("billing_checkout", { plan: "pro", seats: 1, student: false })`) and marks the
 * account paid from the webhook, which is all the cap logic needs. Until billing is
 * switched on, this reports that subscriptions aren't open yet.
 */
export async function startSubscription(): Promise<SubscribeResult> {
  return { ok: false, reason: "not_connected" };
}
