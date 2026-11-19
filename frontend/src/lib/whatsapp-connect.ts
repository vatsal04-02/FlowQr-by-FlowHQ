import { api } from "./api";
import { launchEmbeddedSignup, type SignupStart } from "./whatsapp";

/** The whole connect flow, used by the Connect page and the set-up wizard: start on the server, open Meta's window, finish on the server. Throws an Error with a plain-words message. */
export async function connectWhatsApp(): Promise<void> {
  const start = await api<SignupStart>("/whatsapp/connect/start", { method: "POST" });
  const got = await launchEmbeddedSignup(start);
  await api("/whatsapp/connect/complete", { method: "POST", body: { state: start.state, code: got.code, waba_id: got.waba_id, phone_number_id: got.phone_number_id } });
}
