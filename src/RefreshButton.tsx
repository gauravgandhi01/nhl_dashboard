import { RefreshCw } from "lucide-react";

export function RefreshButton({
  label,
  ariaLabel,
  description,
  busy = false,
  disabled = false,
  onClick,
}: {
  label: string;
  ariaLabel?: string;
  description: string;
  busy?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="refresh-button"
      aria-label={ariaLabel || `Refresh ${label.toLowerCase()}`}
      aria-busy={busy}
      title={description}
      disabled={busy || disabled}
      onClick={onClick}
    >
      <RefreshCw size={13} className={busy ? "spin" : ""} aria-hidden="true" />
      {label}
    </button>
  );
}
