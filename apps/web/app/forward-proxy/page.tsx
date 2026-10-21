"use client";

import { Check, ChevronDown, Code2, Copy, Globe2, Puzzle } from "lucide-react";
import { useEffect, useState } from "react";
import { fetchGateway, fetchGatewayTrust } from "@/lib/api/gateway";
import type { GatewayView, TrustManifest } from "@/lib/api/gateway";
import { useVerifiedSession } from "@/lib/auth/session-context";

type Platform = "windows" | "macos" | "linux";
type WindowsMode = "gui" | "powershell";
type MacMode = "gui" | "terminal";
type LinuxDistribution = "debian" | "fedora";
type Application = "firefox" | "opencode" | "cline";
const platforms: { id: Platform; label: string }[] = [
  { id: "windows", label: "Windows 11 and later" },
  { id: "macos", label: "macOS" },
  { id: "linux", label: "Linux" },
];

function forwardProxyOrigins(view: GatewayView): string[] {
  const groups = [
    view.catalog["self-hosted-api-providers"],
    view.catalog["external-api-providers"],
    view.catalog["external-subscription-providers"],
    view.catalog["mcp-servers"],
  ];
  const origins = groups.flatMap((entries) => entries.flatMap((entry) => entry.routes))
    .filter((route) => route.entry_mode === "forward_proxy")
    .map((route) => {
      try {
        const url = new URL(route.url);
        return url.protocol === "https:" && !url.username && !url.password ? url.origin : null;
      } catch {
        return null;
      }
    })
    .filter((origin): origin is string => origin !== null);
  return [...new Set(origins)];
}

function Command({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);

  return <div className="relative overflow-hidden rounded-lg bg-neutral text-neutral-content">
    <button type="button" className="btn btn-ghost btn-xs absolute right-2 top-2 z-10 gap-1.5 text-neutral-content hover:bg-white/15 hover:text-white" onClick={() => {
      void navigator.clipboard.writeText(command).then(() => { setCopied(true); }).catch(() => { setCopied(false); });
    }}>
      {copied ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : <Copy className="h-3.5 w-3.5" aria-hidden="true" />}
      {copied ? "Copied" : "Copy"}
    </button>
    <pre className="overflow-x-auto p-4 pr-24 font-mono text-xs leading-relaxed"><code>{command}</code></pre>
  </div>;
}

export default function ForwardProxyPage() {
  const session = useVerifiedSession();
  const { gateway_trust_available } = session;
  const [manifest, setManifest] = useState<TrustManifest | null>(null);
  const [gateway, setGateway] = useState<GatewayView | null>(null);
  const [gatewayLoaded, setGatewayLoaded] = useState(false);
  const [loading, setLoading] = useState(gateway_trust_available !== false);
  const [platform, setPlatform] = useState<Platform>("windows");
  const [windowsMode, setWindowsMode] = useState<WindowsMode>("gui");
  const [macMode, setMacMode] = useState<MacMode>("gui");
  const [linuxDistribution, setLinuxDistribution] = useState<LinuxDistribution>("debian");
  const [selected, setSelected] = useState<string | null>(null);
  const [expandedApp, setExpandedApp] = useState<Application | null>("opencode");
  const [selectedProxy, setSelectedProxy] = useState<string | null>(null);

  useEffect(() => {
    if (gateway_trust_available === false) return;
    const controller = new AbortController();
    fetchGatewayTrust(controller.signal)
      .then((value) => { setManifest(value); })
      .catch(() => { if (!controller.signal.aborted) setManifest(null); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => { controller.abort(); };
  }, [gateway_trust_available]);

  useEffect(() => {
    const controller = new AbortController();
    fetchGateway(false, controller.signal)
      .then((value) => { setGateway(value); })
      .catch(() => { if (!controller.signal.aborted) setGateway(null); })
      .finally(() => { if (!controller.signal.aborted) setGatewayLoaded(true); });
    return () => { controller.abort(); };
  }, [session]);

  const current = manifest?.versions.find((item) => item.version === manifest.current_version);
  const certificate = current?.certificates.find((item) => item.fingerprint_sha256 === selected) ?? current?.certificates[0];
  const stamp = certificate ? new Date(certificate.not_before).toISOString().slice(0, 10).replaceAll("-", "") : "";
  const name = certificate ? `neurwerk-root-${stamp}-${certificate.fingerprint_sha256.slice(0, 8)}` : "";
  const file = `${name}.cer`;
  const linuxFile = `${name}.crt`;
  const certificatePath = certificate ? `/api/gateway/trust/certificates/${encodeURIComponent(certificate.fingerprint_sha256)}.cer` : "";
  const downloadUrl = certificate && typeof window !== "undefined" ? new URL(certificatePath, window.location.origin).toString() : "";
  const windowsPath = `Join-Path $env:USERPROFILE 'Downloads\\${file}'`;
  const unixPath = `"$HOME/Downloads/${file}"`;
  const curl = platform === "windows"
    ? `curl.exe --fail --location --output "$env:USERPROFILE\\Downloads\\${file}" "${downloadUrl}"`
    : `curl --fail --location --output ${unixPath} "${downloadUrl}"`;

  const verify = platform === "windows"
    ? `$cert = ${windowsPath}\n(Get-FileHash -Algorithm SHA256 $cert).Hash`
    : platform === "macos" ? `shasum -a 256 ${unixPath}` : `sha256sum ${unixPath}`;
  const install = platform === "windows"
    ? `$cert = ${windowsPath}\nImport-Certificate -FilePath $cert -CertStoreLocation Cert:\\LocalMachine\\Root`
    : `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ${unixPath}`;
  const linuxInstall = `openssl x509 -inform DER -in ${unixPath} -out "$HOME/Downloads/${linuxFile}"\n${linuxDistribution === "debian"
    ? `sudo install -m 0644 "$HOME/Downloads/${linuxFile}" /usr/local/share/ca-certificates/${linuxFile}\nsudo update-ca-certificates`
    : `sudo install -m 0644 "$HOME/Downloads/${linuxFile}" /etc/pki/ca-trust/source/anchors/${linuxFile}\nsudo update-ca-trust extract`}`;
  const proxyOrigins = gateway ? forwardProxyOrigins(gateway) : [];
  const proxyOrigin = selectedProxy && proxyOrigins.includes(selectedProxy) ? selectedProxy : proxyOrigins[0];

  return <main className="mx-auto max-w-4xl space-y-6 p-4 sm:p-6">
    <h1 className="text-2xl font-semibold tracking-tight">Forward-Proxy</h1>
    {!certificate || !current ? <p role="status" className="text-sm text-muted-foreground">
      {loading ? "Loading certificates…" : "Certificates unavailable."}
    </p> : <>
      <section className="card space-y-4 border border-border bg-card p-4 sm:p-6" aria-labelledby="install-heading">
        <h2 id="install-heading" className="text-lg font-semibold">1. Install the forward-proxy root certificate</h2>
        <div role="tablist" aria-label="Operating system" className="tabs tabs-border flex-wrap">
          {platforms.map((item) => <button key={item.id} type="button" role="tab" id={`tab-${item.id}`}
            aria-controls="installation-commands" aria-selected={platform === item.id}
            className={`tab ${platform === item.id ? "tab-active" : ""}`} onClick={() => { setPlatform(item.id); }}>
            {item.label}
          </button>)}
        </div>
        <div id="installation-commands" role="tabpanel" aria-labelledby={`tab-${platform}`} className="space-y-4">
          {current.certificates.length > 1 && <div className="space-y-2">
            <p className="text-sm font-medium">Choose a certificate and repeat these steps for each one:</p>
            <div className="flex flex-wrap gap-2">
              {current.certificates.map((root) => <button key={root.fingerprint_sha256} type="button"
                className={`btn btn-sm ${root.fingerprint_sha256 === certificate.fingerprint_sha256 ? "btn-primary" : "btn-outline"}`}
                aria-pressed={root.fingerprint_sha256 === certificate.fingerprint_sha256}
                onClick={() => { setSelected(root.fingerprint_sha256); }}>
                {root.state === "active" ? "Current certificate" : "Other certificate"}
              </button>)}
            </div>
          </div>}
          <section className="space-y-3 rounded-lg border border-border p-4" aria-labelledby="download-step">
            <h3 id="download-step" className="text-base font-semibold">1. Download the certificate</h3>
            <a className="link link-primary text-sm" href={certificatePath}>Download certificate (.cer)</a>
            <p className="pt-2 text-sm leading-relaxed">Or download with curl {platform === "windows" ? "in PowerShell" : "in a terminal"}:</p>
            <Command key={`${platform}-${file}-curl`} command={curl} />
          </section>
          <section className="space-y-3 rounded-lg border border-border p-4" aria-labelledby="verify-step">
            <h3 id="verify-step" className="text-base font-semibold">2. Check the fingerprint (Recommended)</h3>
            <Command key={`${platform}-${file}-verify`} command={verify} />
            <p className="text-sm leading-relaxed">The result must match this fingerprint and the one your administrator provides. If not, do not install it.</p>
            <p className="break-all font-mono text-xs">{certificate.fingerprint_sha256}</p>
          </section>
          <section className="space-y-3 rounded-lg border border-border p-4" aria-labelledby="install-step">
            <h3 id="install-step" className="text-base font-semibold">3. Install the certificate</h3>
            {platform === "windows" ? <>
              <div className="join" aria-label="Windows installation method">
                <button type="button" className={`btn btn-sm join-item ${windowsMode === "gui" ? "btn-primary" : "btn-outline"}`}
                  aria-pressed={windowsMode === "gui"} onClick={() => { setWindowsMode("gui"); }}>Windows GUI</button>
                <button type="button" className={`btn btn-sm join-item ${windowsMode === "powershell" ? "btn-primary" : "btn-outline"}`}
                  aria-pressed={windowsMode === "powershell"} onClick={() => { setWindowsMode("powershell"); }}>PowerShell</button>
              </div>
              {windowsMode === "gui" ? <ol className="list-decimal space-y-2 pl-5 text-sm leading-relaxed">
                <li>Open <span className="font-mono break-all">{file}</span> from your Downloads folder and click <strong>Install Certificate</strong>.</li>
                <li>Select <strong>Local Machine</strong> and approve the administrator prompt.</li>
                <li>Choose <strong>Place all certificates in the following store</strong>, then <strong>Browse</strong> and select <strong>Trusted Root Certification Authorities</strong>.</li>
                <li>Click <strong>Next</strong>, then <strong>Finish</strong>. Confirm the security warning only if the fingerprint matched in step 2.</li>
              </ol> : <>
                <p className="text-sm text-muted-foreground">Run PowerShell as Administrator:</p>
                <Command key={`${file}-install`} command={install} />
              </>}
            </> : platform === "macos" ? <>
              <div className="join" aria-label="macOS installation method">
                <button type="button" className={`btn btn-sm join-item ${macMode === "gui" ? "btn-primary" : "btn-outline"}`}
                  aria-pressed={macMode === "gui"} onClick={() => { setMacMode("gui"); }}>Keychain Access</button>
                <button type="button" className={`btn btn-sm join-item ${macMode === "terminal" ? "btn-primary" : "btn-outline"}`}
                  aria-pressed={macMode === "terminal"} onClick={() => { setMacMode("terminal"); }}>Terminal</button>
              </div>
              {macMode === "gui" ? <ol className="list-decimal space-y-2 pl-5 text-sm leading-relaxed">
                <li>Open <strong>Keychain Access</strong>, select the <strong>System</strong> keychain, then use <strong>File → Import Items</strong> to import <span className="font-mono break-all">{file}</span> from Downloads.</li>
                <li>Double-click the imported certificate, expand <strong>Trust</strong>, and set <strong>When using this certificate</strong> to <strong>Always Trust</strong>.</li>
                <li>Close the window and approve the administrator prompt to save your changes.</li>
              </ol> : <Command key={`${file}-mac-install`} command={install} />}
            </> : <>
              <div className="join" aria-label="Linux distribution">
                <button type="button" className={`btn btn-sm join-item ${linuxDistribution === "debian" ? "btn-primary" : "btn-outline"}`}
                  aria-pressed={linuxDistribution === "debian"} onClick={() => { setLinuxDistribution("debian"); }}>Debian / Ubuntu</button>
                <button type="button" className={`btn btn-sm join-item ${linuxDistribution === "fedora" ? "btn-primary" : "btn-outline"}`}
                  aria-pressed={linuxDistribution === "fedora"} onClick={() => { setLinuxDistribution("fedora"); }}>Fedora / RHEL</button>
              </div>
              <Command key={`${linuxDistribution}-${file}-install`} command={linuxInstall} />
            </>}
          </section>
        </div>
      </section>
      <section className="card space-y-4 border border-border bg-card p-4 sm:p-6" aria-labelledby="applications-heading">
        <h2 id="applications-heading" className="text-lg font-semibold">2. Configure your applications</h2>
        <div className="space-y-3">
          {([
            ["opencode", "OpenCode", Code2],
            ["firefox", "Firefox", Globe2],
            ["cline", "Cline", Puzzle],
          ] as const).map(([id, label, Icon]) => <div key={id} className="overflow-hidden rounded-lg border border-border">
            <h3>
              <button type="button" aria-expanded={expandedApp === id} aria-controls={`${id}-instructions`}
                onClick={() => { setExpandedApp(expandedApp === id ? null : id); }}
                className="flex w-full items-center justify-between gap-3 p-4 text-left text-sm transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-primary">
                <span className="flex items-center gap-3 font-medium"><Icon className="h-5 w-5 text-primary" aria-hidden="true" />{label}</span>
                <span className="flex items-center gap-2">
                  {id !== "opencode" && <span className="badge badge-outline">Coming soon</span>}
                  <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${expandedApp === id ? "rotate-180" : ""}`} aria-hidden="true" />
                </span>
              </button>
            </h3>
            <div id={`${id}-instructions`} hidden={expandedApp !== id} className="space-y-4 border-t border-border p-4">
              {id === "opencode" ? <>
                <section className="space-y-3 rounded-lg border border-border p-4">
                  <h4 className="text-base font-semibold">1. Get an access key</h4>
                  <p className="text-sm leading-relaxed">Use a <a className="link link-primary" href="/api-keys">Neurwerk access key</a> as the proxy password. The username can be anything. URL-encode special characters in the key.</p>
                </section>
                <section className="space-y-3 rounded-lg border border-border p-4">
                  <h4 className="text-base font-semibold">2. Set the proxy address</h4>
                  {proxyOrigins.length > 1 && <label className="block space-y-1 text-sm">
                    <span className="font-medium">Proxy address</span>
                    <select className="select select-bordered w-full" value={proxyOrigin} onChange={(event) => { setSelectedProxy(event.target.value); }}>
                      {proxyOrigins.map((origin) => <option key={origin} value={origin}>{origin}</option>)}
                    </select>
                  </label>}
                  {proxyOrigin ? <>
                    {proxyOrigins.length === 1 && <p className="break-all text-sm">Proxy address: <span className="font-mono">{proxyOrigin}</span></p>}
                    <p className="text-sm leading-relaxed">Replace <code className="font-mono">{"<URL-encoded-key>"}</code> with your URL-encoded Neurwerk access key, then configure OpenCode V2’s background service:</p>
                    <Command key={proxyOrigin} command={`opencode service set env HTTPS_PROXY 'https://user:<URL-encoded-key>@${new URL(proxyOrigin).host}'\nopencode service set env NO_PROXY localhost,127.0.0.1,::1`} />
                  </> : <p role="status" className="text-sm">{gatewayLoaded
                    ? <>No forward-proxy address is available for your account. Check <a className="link link-primary" href="/documentation/developers/endpoints">Endpoints</a> or ask your administrator.</>
                    : "Loading proxy address…"}</p>}
                </section>
                {proxyOrigin && <section className="space-y-3 rounded-lg border border-border p-4">
                  <h4 className="text-base font-semibold">3. Start OpenCode</h4>
                  <Command command="opencode service start" />
                </section>}
              </> : <p className="text-sm">Coming soon.</p>}
            </div>
          </div>)}
        </div>
      </section>
    </>}
  </main>;
}
