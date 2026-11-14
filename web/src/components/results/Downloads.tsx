import { DownloadIcon } from "@/components/ui/icons";
import { resolveArtifactUrl, type DataSource } from "@/lib/api";
import type { Download } from "@/lib/types";

/** Files produced by an analysis. Sample results have no files behind them, so the list is shown but inactive. */
export function Downloads({ downloads, source }: { downloads: Download[]; source: DataSource }) {
  const sample = source === "demo";
  return (
    <div>
      <ul className="divide-y divide-line rounded-xl border border-line">
        {downloads.map((download) => {
          const body = (
            <>
              <DownloadIcon className="mt-0.5 shrink-0" />
              <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{download.label}</span>
              <span className="max-w-24 shrink-0 truncate text-[13px] text-ink-3" title={download.format}>
                {download.format}
              </span>
            </>
          );
          return (
            <li key={download.url}>
              {sample ? (
                <span className="flex items-start gap-2.5 px-3.5 py-2.5 text-sm leading-snug text-ink-3">{body}</span>
              ) : (
                <a
                  className="flex items-start gap-2.5 px-3.5 py-2.5 text-sm leading-snug text-ink hover:bg-raised"
                  href={resolveArtifactUrl(download.url, source)}
                  download
                  target="_blank"
                  rel="noreferrer"
                >
                  {body}
                </a>
              )}
            </li>
          );
        })}
      </ul>
      {sample ? <p className="mt-2 text-sm text-ink-3">Downloads are not available for sample data.</p> : null}
    </div>
  );
}
