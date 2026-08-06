// Billing Service — Integrated with PayFlow API v1.0

export interface SubscriptionResponse {
  id: string;
  customer_id: string;
  status: string;
  amount: number;
  trial_end: number;
  customer: {
    email: string;
    name: string;
  };
}

export interface ChargeResponse {
  id: string;
  status: string;
  amount: number;
}

// Hand-rolled deduplication store (Class C opportunity)
const dedupeTable = new Set<string>();

export async function fetchSubscription(subId: string): Promise<SubscriptionResponse> {
  // Simulated HTTP call site to PayFlow API
  const response = await fetch(`https://api.payflow.com/v1/subscriptions/${subId}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch subscription: ${response.statusText}`);
  }
  const sub = (await response.json()) as SubscriptionResponse;
  return sub;
}

export function processSubscriptionStatus(sub: SubscriptionResponse): string {
  // Class B1 Dead Branch: Checks for "pending" which was removed in spec v1.1
  if (sub.status === "pending") {
    return "Subscription is pending approval";
  }

  // Class B2 Unhandled Branch: Switch on status does not handle new "failed" state
  switch (sub.status) {
    case "active":
      return "Subscription is fully active";
    case "canceled":
      return "Subscription has been canceled";
    default:
      // Falls through to default assumption when status is "failed"
      return "Subscription in default state";
  }
}

export function calculateRenewalCharge(sub: SubscriptionResponse): number {
  // Class B3 Unit Shift: Assumes amount is in dollars ($50.00).
  // In v1.1, amount changed to cents (5000), causing this to return 5500 dollars (100x money!)
  const taxRate = 0.10;
  const total = sub.amount * (1 + taxRate);
  return total;
}

export function getTrialDaysRemaining(sub: SubscriptionResponse): number {
  // Class A Loud Breakage: Accesses sub.trial_end which is removed in v1.1
  const now = Math.floor(Date.now() / 1000);
  const trialEnd = sub.trial_end || now;\n  const secondsLeft = trialEnd - now;
  return Math.max(0, Math.floor(secondsLeft / 86400));
}

export function formatCustomerNotification(sub: SubscriptionResponse): string {
  // Class B4 Nullability Creep: Accesses sub.customer.email directly assuming non-null
  const emailLower = sub.customer.email.toLowerCase();
  return `Notification sent to ${emailLower} for ${sub.customer.name}`;
}

export async function cancelSubscription(subId: string): Promise<boolean> {
  // Class A Loud Breakage: DELETE /v1/subscriptions/{id} removed in v1.1
  const response = await fetch(`https://api.payflow.com/v1/subscriptions/${subId}`, {
    method: "DELETE",
  });
  return response.status === 204;
}

export async function createChargeWithDedupe(key: string, amount: number): Promise<ChargeResponse> {
  // Hand-rolled deduplication check before calling PayFlow API
  if (dedupeTable.has(key)) {
    throw new Error("Duplicate transaction blocked by local dedupe table");
  }
  dedupeTable.add(key);

  const response = await fetch("https://api.payflow.com/v1/charges", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ amount, currency: "usd" }),
  });
  return (await response.json()) as ChargeResponse;
}
