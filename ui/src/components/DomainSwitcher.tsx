import type { BrainInfo } from "../lib/api";

interface Props {
  brains: BrainInfo[];
  active: string;
  onChange: (id: string) => void;
}

export default function DomainSwitcher({ brains, active, onChange }: Props) {
  return (
    <div className="domains" role="tablist" aria-label="Domain brain">
      {brains.map((b) => (
        <button
          key={b.id}
          role="tab"
          aria-selected={active === b.id}
          data-on={active === b.id}
          className="domain-opt"
          onClick={() => onChange(b.id)}
        >
          {b.label}
        </button>
      ))}
    </div>
  );
}
