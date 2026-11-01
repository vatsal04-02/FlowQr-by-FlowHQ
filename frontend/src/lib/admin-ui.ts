export interface TenantRow {
  id: string; name: string; category: string | null; created_at: string; is_active: boolean; suspension_reason: string | null; support_status: string;
  owner_email: string | null; plan: string | null; subscription_status: string | null; locations: number; cards: number; members: number;
}
export const SUB_TONE: Record<string, "green" | "blue" | "amber" | "red" | "gray"> = { active: "green", trialing: "blue", manual: "green", past_due: "amber", halted: "red", expired: "red", canceled: "gray", pending: "gray" };
