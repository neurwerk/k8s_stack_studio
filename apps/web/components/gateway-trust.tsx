import type { TrustManifest } from "@/lib/api/gateway";
import { certificateValidity } from "@/lib/gateway-view";

export function GatewayTrust({ manifest, loading, now, compact = false }: {
  manifest: TrustManifest | null;
  loading: boolean;
  now: number;
  compact?: boolean;
}) {
  const current = manifest?.versions.find((item) => item.version === manifest.current_version);
  if (compact) return <div className="flex flex-wrap gap-2">
    {current ? <>
      <a className="btn btn-primary btn-sm" href={`/api/gateway/trust/bundles/${encodeURIComponent(current.version)}.pem`}>Download certificate bundle (.pem)</a>
      {current.certificates.map((certificate) => <a key={certificate.fingerprint_sha256} className="btn btn-outline btn-sm"
        href={`/api/gateway/trust/certificates/${encodeURIComponent(certificate.fingerprint_sha256)}.cer`}>
        Download {certificate.state} certificate (.cer)
      </a>)}
    </> : <p role="status" className="text-sm text-muted-foreground">{loading ? "Loading certificates…" : "Certificates unavailable."}</p>}
  </div>;
  return <section className="card border border-border bg-card p-4 sm:p-6" aria-labelledby="gateway-trust-heading">
    <h2 id="gateway-trust-heading" className="text-lg font-semibold">Inspection trust</h2>
    <p className="mt-1 text-sm text-muted-foreground">
      Public inspection roots for approved proxy operations. These downloads use Studio’s independently trusted HTTPS address.
      Certificate publication does not confirm that a gateway has loaded its signer.
      Retained downloads are not a recommendation to install expired roots.
    </p>
    {!current ? <p role="status" className="mt-4 text-sm text-muted-foreground">
      {loading ? "Loading public trust…" : "Public trust unavailable. Retry to check the current publication."}
    </p> : <>
      {current.certificates.some((certificate) => certificateValidity(certificate, now) !== "Within validity dates") &&
        <p role="status" className="mt-3 text-sm text-destructive">Current root health unavailable: check certificate validity.</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <a className="btn btn-primary btn-sm" href={`/api/gateway/trust/bundles/${encodeURIComponent(current.version)}.pem`}>
          Download this root bundle
        </a>
        <a className="btn btn-outline btn-sm" href="/api/gateway/trust/manifest.json">Public manifest</a>
      </div>
      <dl className="mt-3 space-y-1 text-xs">
        <div><dt className="text-muted-foreground">Bundle SHA-256 / version</dt>
          <dd className="break-all font-mono">{current.bundle_sha256}</dd></div>
        <div><dt className="text-muted-foreground">Published</dt><dd>{current.published_at}</dd></div>
      </dl>
      <ul className="mt-4 space-y-3">
        {current.certificates.map((certificate) => <li key={certificate.fingerprint_sha256}
          className="rounded-lg border border-border p-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="badge badge-outline">{certificate.state === "active" ? "Active root" : "Transitional root"}</span>
            <span>{certificateValidity(certificate, now)}</span>
            <a className="link link-primary ml-auto" href={`/api/gateway/trust/certificates/${encodeURIComponent(certificate.fingerprint_sha256)}.cer`}>
              Download .cer (DER)
            </a>
          </div>
          <p className="mt-2 text-xs text-muted-foreground">Certificate SHA-256 (DER)</p>
          <p className="break-all font-mono text-xs">{certificate.fingerprint_sha256}</p>
          <p className="mt-2 break-words text-xs text-muted-foreground">
            Valid from {certificate.not_before} to {certificate.not_after}
          </p>
        </li>)}
      </ul>
      {manifest && manifest.versions.length > 1 && <details className="mt-4">
        <summary className="cursor-pointer text-sm font-medium">Retained bundles</summary>
        <ul className="mt-2 space-y-2 text-xs">
          {manifest.versions.filter((item) => item.version !== current.version).map((item) => <li key={item.version}>
            <a className="link link-primary break-all font-mono" href={`/api/gateway/trust/bundles/${encodeURIComponent(item.version)}.pem`}>
              {item.version}
            </a>
            <span className="ml-2 text-muted-foreground">Published {item.published_at}</span>
          </li>)}
        </ul>
      </details>}
    </>}
  </section>;
}
