import { invoke } from "@tauri-apps/api/core";
import { errorCode } from "../../lib/errors";
import type { Interval } from "./access";

export type SubscribeResult = "opened" | "not_connected" | "failed";

/**
 * The one entry point for "Subscribe" (upgrade screen and Account): opens Stripe Checkout in
 * the browser for Nudgy Pro, monthly or yearly. The server marks the account paid from
 * Stripe's webhook; the app picks it up when the browser hands back (nudgy://billing).
 */
export async function startSubscription(interval: Interval): Promise<SubscribeResult> {
  try {
    await invoke("billing_checkout", { plan: "pro", seats: 1, student: false, interval });
    return "opened";
  } catch (e) {
    return errorCode(e) === "config" ? "not_connected" : "failed";
  }
}
