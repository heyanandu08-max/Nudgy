import { invoke } from "@tauri-apps/api/core";
import { errorCode } from "../../lib/errors";
import type { Interval } from "./access";

export type SubscribeResult = "opened" | "not_connected" | "failed";

/**
 * The one entry point for "Subscribe" (upgrade screen and Account): opens PayPal in the
 * browser to approve Nudgy Pro, monthly or yearly. The server confirms the subscription with
 * PayPal (return page + webhook); the app picks it up when the browser hands back
 * (nudgy://billing).
 */
export async function startSubscription(interval: Interval): Promise<SubscribeResult> {
  try {
    await invoke("billing_checkout", { plan: "pro", seats: 1, interval });
    return "opened";
  } catch (e) {
    return errorCode(e) === "config" ? "not_connected" : "failed";
  }
}
