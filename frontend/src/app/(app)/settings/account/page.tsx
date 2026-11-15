"use client";
import { useEffect, useState } from "react";
import { useGoogleError } from "@/components/GoogleAuth";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, PageHeader } from "@/components/ui/Card";
import { ErrorSummary, Input } from "@/components/ui/Form";
import { KV, Panel } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { passwordRule, phoneRule, required, useForm } from "@/lib/form";

/** Settings › Account (PRD §5.4): you, not the business: your profile, how you sign in, your password. Google sign-in returns here. */
export default function AccountPage() {
  const { me, refresh } = useAuth();
  if (!me) return null;
  return (
    <>
      <PageHeader title="Account" subtitle="Your own profile and how you sign in. These apply to every business you belong to." />
      <div className="max-w-3xl space-y-6">
        <ProfilePanels email={me.user.email} name={me.user.full_name ?? ""} phone={me.user.phone ?? ""}
          hasLocalLogin={me.user.has_local_login ?? true} googleLinked={me.user.google_linked ?? false} onSaved={refresh} />
      </div>
    </>
  );
}

function ProfilePanels({ email, name, phone, hasLocalLogin, googleLinked, onSaved }: { email: string; name: string; phone: string; hasLocalLogin: boolean; googleLinked: boolean; onSaved: () => Promise<unknown> }) {
  const toast = useToast();
  const p = useForm({ full_name: name, phone }, { full_name: required("Name"), phone: phoneRule });
  const pw = useForm({ current_password: "", new_password: "" }, { current_password: required("Current password"), new_password: passwordRule });
  const first = useForm({ new_password: "" }, { new_password: passwordRule });
  const [b1, setB1] = useState(false), [b2, setB2] = useState(false), [b3, setB3] = useState(false), [b4, setB4] = useState(false);
  const googleError = useGoogleError();
  const [linkError, setLinkError] = useState<string | null>(null);
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("google") === "linked") {
      toast("Google account connected.");
      void onSaved();
      window.history.replaceState(null, "", window.location.pathname + window.location.hash);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function connectGoogle() {
    setB4(true); setLinkError(null);
    try {
      const { auth_url } = await api<{ auth_url: string }>("/auth/google/link", { method: "POST" });
      window.location.href = auth_url; // full redirect to Google
    } catch (err) { setLinkError(errorMessage(err)); setB4(false); }
  }

  return (
    <>
      <section id="signin" className="scroll-mt-6"><Panel title="Sign-in methods" meta="how you can log in to FlowQR">
        <div className="space-y-4">
          {(googleError || linkError) && <Alert tone="error" title="Google wasn't connected">{googleError ?? linkError}</Alert>}
          <KV rows={[
            ["Email and password", hasLocalLogin ? <Badge key="pw" tone="green">On</Badge> : <Badge key="pw">Not set</Badge>],
            ["Google", googleLinked ? <Badge key="g" tone="green">Connected</Badge> : <Badge key="g">Not connected</Badge>],
          ]} />
          {!googleLinked && <Button variant="secondary" loading={b4} onClick={() => void connectGoogle()}>Connect Google account</Button>}
          <p className="text-xs text-ink-500">This only lets you sign in with Google. It is separate from connecting your Google Business Profile for reviews.</p>
        </div></Panel></section>
      <section id="you" className="scroll-mt-6"><Panel title="Your profile" meta={email}>
        <form noValidate className="space-y-4" onSubmit={async (e) => { e.preventDefault(); if (!p.validateAll()) return; setB1(true); try { await api("/auth/profile", { method: "PATCH", body: { full_name: p.values.full_name.trim(), phone: p.values.phone.trim() || null } }); await onSaved(); toast("Profile saved."); } catch (err) { p.fail(errorMessage(err)); } finally { setB1(false); } }}>
          <ErrorSummary errors={p.errors} serverError={p.serverError} summaryRef={p.summaryRef} />
          <div className="grid gap-4 sm:grid-cols-2"><Input label="Your name" {...p.bind("full_name")} /><Input label="Mobile" type="tel" {...p.bind("phone")} /></div>
          <Button type="submit" loading={b1}>Save profile</Button>
        </form></Panel></section>
      {!hasLocalLogin ? (
        <section id="password" className="scroll-mt-6"><Panel title="Set a password" meta="optional: lets you also log in with your email; other devices will be signed out">
          <form noValidate className="space-y-4" onSubmit={async (e) => { e.preventDefault(); if (!first.validateAll()) return; setB3(true); try { await api("/auth/set-password", { method: "POST", body: first.values }); first.setValues({ new_password: "" }); await onSaved(); toast("Password set."); } catch (err) { first.fail(errorMessage(err)); } finally { setB3(false); } }}>
            <ErrorSummary errors={first.errors} serverError={first.serverError} summaryRef={first.summaryRef} />
            <Input label="New password" type="password" autoComplete="new-password" hint="At least 10 characters with upper and lower case letters." {...first.bind("new_password")} />
            <Button type="submit" loading={b3}>Set password</Button>
          </form></Panel></section>
      ) : (
      <section id="password" className="scroll-mt-6"><Panel title="Change password" meta="other devices will be signed out">
        <form noValidate className="space-y-4" onSubmit={async (e) => { e.preventDefault(); if (!pw.validateAll()) return; setB2(true); try { await api("/auth/change-password", { method: "POST", body: pw.values }); pw.setValues({ current_password: "", new_password: "" }); toast("Password changed."); } catch (err) { pw.fail(errorMessage(err)); } finally { setB2(false); } }}>
          <ErrorSummary errors={pw.errors} serverError={pw.serverError} summaryRef={pw.summaryRef} />
          <div className="grid gap-4 sm:grid-cols-2"><Input label="Current password" type="password" autoComplete="current-password" {...pw.bind("current_password")} /><Input label="New password" type="password" autoComplete="new-password" {...pw.bind("new_password")} /></div>
          <Button type="submit" loading={b2}>Change password</Button>
        </form></Panel></section>
      )}
    </>
  );
}
