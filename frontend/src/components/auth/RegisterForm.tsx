"use client";
import { Check } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { GoogleSignIn, useGoogleError } from "@/components/GoogleAuth";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { ErrorSummary, Input, PasswordInput } from "@/components/ui/Form";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { emailRule, passwordRule, phoneRule, required, useForm } from "@/lib/form";
import { usePlans } from "@/lib/plans";

/**
 * The sign-up form, shared by the full Sign up page (/register) and the sign-up popup on the pricing page, so both run exactly the same checks and the same server call.
 * `useRegister` holds the state and the submit; `RegisterFields` draws the form. Who may register is decided by the backend (REGISTRATION_MODE): this only tells people before they type a password.
 */

/** The two password rules, ticked off as they are met. Colour is never the only signal: each line starts with a tick or a dot and says "met" to screen readers. */
function PasswordRules({ value }: { value: string }) {
  const rules: [string, boolean][] = [["10 or more characters", value.length >= 10], ["Both upper and lower case letters", /[a-z]/.test(value) && /[A-Z]/.test(value)]];
  return (
    <ul className="mt-2 space-y-1 text-[13px]" aria-label="Password rules">
      {rules.map(([t, ok]) => (
        <li key={t} className={ok ? "flex items-center gap-2 text-[#157347]" : "flex items-center gap-2 text-ink-500"}>
          {ok ? <Check className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden /> : <span aria-hidden className="mx-1 h-1.5 w-1.5 rounded-full bg-ink-300" />}{t}<span className="sr-only">{ok ? ", met" : ", not met yet"}</span>
        </li>
      ))}
    </ul>
  );
}

export function useRegister() {
  const { refresh } = useAuth();
  const router = useRouter();
  const { mandateRequired, trialDays } = usePlans();
  const [busy, setBusy] = useState(false);
  // "I confirm that I am 18 years of age or older": never pre-ticked; the server refuses sign-up without it (backend/app/api/v1/auth.py) and no date of birth is collected.
  const [age, setAge] = useState(false);
  const [ageErr, setAgeErr] = useState(false);
  const ageRef = useRef<HTMLInputElement>(null);
  const needAge = () => { setAgeErr(true); ageRef.current?.focus(); };
  const f = useForm({ full_name: "", email: "", phone: "", password: "" }, {
    full_name: required("Your name"), email: emailRule, password: passwordRule, phone: phoneRule,
  });

  const [mode, setMode] = useState<"open" | "allowlist" | "closed" | null>(null);
  useEffect(() => {
    api<{ mode: "open" | "allowlist" | "closed" }>("/auth/registration").then((r) => setMode(r.mode)).catch(() => setMode("open"));
  }, []);

  const googleError = useGoogleError();
  useEffect(() => { if (googleError) f.fail(googleError); }, [googleError]); // eslint-disable-line react-hooks/exhaustive-deps

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    f.setServerError(null);
    if (!f.validateAll()) return;
    if (!age) { needAge(); return; }
    setBusy(true);
    try {
      const v = f.values;
      await api("/auth/register", { method: "POST", body: { full_name: v.full_name.trim(), email: v.email.trim(), phone: v.phone.trim() || null, password: v.password, age_confirmed: true } });
      if (!(await refresh())) { f.fail("Your account was created, but your browser did not keep the session. Allow cookies for flowqr.site, then log in."); return; }
      router.replace("/onboarding");
    } catch (err) { f.fail(errorMessage(err)); } finally { setBusy(false); }
  }

  return { mode, mandateRequired, trialDays, busy, age, setAge, ageErr, setAgeErr, ageRef, needAge, f, submit };
}
export type Register = ReturnType<typeof useRegister>;

export const ClosedNote = () => (
  <Alert tone="info">FlowQR is open to approved businesses only at the moment. If you expected access, contact FlowQR support. If you already have an account, log in.</Alert>
);

export function RegisterFields({ r }: { r: Register }) {
  const { f, age, setAge, ageErr, setAgeErr, ageRef, needAge, busy, submit, mode } = r;
  return (
    <>
      {mode === "allowlist" && <div className="mb-4"><Alert tone="info">FlowQR is open to approved businesses only at the moment. Register with the email address you gave us. Other addresses are not accepted yet.</Alert></div>}
      <div className="mb-4">
        <label htmlFor="age-confirm" className="flex min-h-11 cursor-pointer items-start gap-3 rounded-lg border border-ink-200 bg-white p-3">
          <input ref={ageRef} id="age-confirm" type="checkbox" checked={age} onChange={(e) => { setAge(e.target.checked); if (e.target.checked) setAgeErr(false); }}
            aria-required="true" aria-invalid={ageErr || undefined} aria-describedby={ageErr ? "age-confirm-error" : undefined} className="mt-0.5 h-5 w-5 shrink-0 accent-[#C94C00]" />
          <span className="text-[14px] leading-relaxed text-ink-700">
            I confirm that I am 18 years of age or older.
          </span>
        </label>
        {ageErr && <p id="age-confirm-error" role="alert" className="mt-1.5 text-[13px] font-medium text-[#B3261E]">Please confirm that you are 18 years of age or older to create an account.</p>}
      </div>
      <GoogleSignIn label="Sign up with Google" divider="or sign up with email" ageConfirmed={age} onNeedAge={needAge} />
      <form onSubmit={submit} noValidate className="space-y-4">
        <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
        <Input label="Your name" autoComplete="name" required {...f.bind("full_name")} />
        <Input label="Work email" type="email" autoComplete="email" inputMode="email" required {...f.bind("email")} />
        <Input label="Mobile number (optional)" type="tel" autoComplete="tel" inputMode="tel" placeholder="98765 43210" hint="Indian mobile number" {...f.bind("phone")} />
        <div>
          <PasswordInput label="Password" autoComplete="new-password" required {...f.bind("password")} />
          <PasswordRules value={f.values.password} />
        </div>
        <Button type="submit" size="lg" variant="brand" className="w-full" loading={busy}>Create account</Button>
        <p className="text-center text-[13px] leading-relaxed text-ink-500">By creating an account you agree to our <Link href="/terms" className="underline">Terms</Link> and <Link href="/privacy" className="underline">Privacy Policy</Link>, and to use FlowQR honestly: no fake reviews, no review gating.</p>
      </form>
    </>
  );
}
